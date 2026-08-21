#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <map>
#include <random>
#include <sstream>
#include <string>
#include <vector>

#include "det_yolo11.h"

#undef OBJ_NAME_MAX_SIZE
#undef OBJ_NUMB_MAX_SIZE
#undef OBJ_CLASS_NUM
#undef NMS_THRESH
#undef BOX_THRESH

#include "pose_yolo11.h"
#include "image_utils.h"

static volatile sig_atomic_t g_running = 1;

struct Options {
    std::string det_model = "model/yolo11.torq";
    std::string pose_model = "model/yolo11_pose.torq";
    std::string labels = "model/coco_80_labels_list.txt";
    std::string action_hook = "scripts/action_hook.sh";
    std::string tmp_dir = "/tmp/agent-butler";
    std::string snapshot_path = "/tmp/home_state.json";
    int port = 9000;
    int max_jpeg_bytes = 20 * 1024 * 1024;
    bool emit_events = false;
};

struct FrameHeader {
    std::string room;
    int64_t frame_id = 0;
    int64_t timestamp_ms = 0;
    int64_t jpeg_bytes = 0;
};

struct BraceletData {
    int spo2 = 98;
    int heart_rate = 75;
    int stress = 30;
    int64_t timestamp_ms = 0;
};

// 单个房间的最新检测状态（全屋快照的基本单元）
struct RoomState {
    bool has_person = false;
    bool has_cat = false;
    bool has_dog = false;
    bool fall_like = false;
};

struct RuleState {
    // 全屋状态表：room -> 最新检测结果（每帧更新对应房间）
    std::map<std::string, RoomState> home_state;
    int kitchen_pet_without_person_streak = 0;
    std::map<std::string, int> fall_streak_by_room;
    int health_abnormal_streak = 0;
    int64_t last_bracelet_ms = 0;
    BraceletData bracelet;
    std::map<std::string, int64_t> last_event_ms;
};

static void on_signal(int)
{
    g_running = 0;
}

static int64_t now_ms()
{
    // 用 system_clock（Unix 纪元），不要用 steady_clock（开机单调钟）。
    // now_ms 兜底写入快照 timestamp_ms，Agent 侧 is_night() 用 datetime.fromtimestamp 解析，
    // 若用 steady_clock 会得到 1970 年附近，昼夜规则全部失效。
    using namespace std::chrono;
    return duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
}

static void print_usage(const char *prog)
{
    printf("%s [--det-model path] [--pose-model path] [--labels path] [--port n] "
           "[--action-hook path] [--tmp-dir path] [--snapshot path] [--emit-events]\n", prog);
}

static bool parse_args(int argc, char **argv, Options *opts)
{
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--help" || arg == "-h") {
            print_usage(argv[0]);
            return false;
        }
        if (arg == "--emit-events") {
            opts->emit_events = true;
            continue;
        }
        if (i + 1 >= argc) {
            printf("missing value for %s\n", arg.c_str());
            return false;
        }
        std::string value = argv[++i];
        if (arg == "--det-model") {
            opts->det_model = value;
        } else if (arg == "--pose-model") {
            opts->pose_model = value;
        } else if (arg == "--labels") {
            opts->labels = value;
        } else if (arg == "--port") {
            opts->port = atoi(value.c_str());
        } else if (arg == "--action-hook") {
            opts->action_hook = value;
        } else if (arg == "--tmp-dir") {
            opts->tmp_dir = value;
        } else if (arg == "--snapshot") {
            opts->snapshot_path = value;
        } else {
            printf("unknown option: %s\n", arg.c_str());
            return false;
        }
    }
    return opts->port > 0 && opts->port < 65536;
}

static bool is_valid_room(const std::string &room)
{
    return room == "living_room" || room == "bedroom1" || room == "bedroom2" ||
           room == "kitchen" || room == "bathroom";
}

static bool is_pose_room(const std::string &room)
{
    return room == "bedroom1" || room == "bedroom2" || room == "bathroom";
}

static std::string json_escape(const std::string &value)
{
    std::ostringstream os;
    for (char c : value) {
        switch (c) {
        case '\\': os << "\\\\"; break;
        case '"': os << "\\\""; break;
        case '\n': os << "\\n"; break;
        case '\r': os << "\\r"; break;
        case '\t': os << "\\t"; break;
        default: os << c; break;
        }
    }
    return os.str();
}

static std::string shell_quote(const std::string &value)
{
    std::string out = "'";
    for (char c : value) {
        if (c == '\'') {
            out += "'\\''";
        } else {
            out += c;
        }
    }
    out += "'";
    return out;
}

static bool extract_json_string(const std::string &json, const std::string &key, std::string *out)
{
    std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) {
        return false;
    }
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) {
        return false;
    }
    pos = json.find('"', pos + 1);
    if (pos == std::string::npos) {
        return false;
    }
    size_t end = json.find('"', pos + 1);
    if (end == std::string::npos) {
        return false;
    }
    *out = json.substr(pos + 1, end - pos - 1);
    return true;
}

static bool extract_json_int64(const std::string &json, const std::string &key, int64_t *out)
{
    std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) {
        return false;
    }
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) {
        return false;
    }
    ++pos;
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) {
        ++pos;
    }
    size_t end = pos;
    if (end < json.size() && json[end] == '-') {
        ++end;
    }
    while (end < json.size() && json[end] >= '0' && json[end] <= '9') {
        ++end;
    }
    if (end == pos) {
        return false;
    }
    *out = strtoll(json.substr(pos, end - pos).c_str(), NULL, 10);
    return true;
}

static bool parse_frame_header(const std::string &line, FrameHeader *header)
{
    return extract_json_string(line, "room", &header->room) &&
           extract_json_int64(line, "frame_id", &header->frame_id) &&
           extract_json_int64(line, "timestamp_ms", &header->timestamp_ms) &&
           extract_json_int64(line, "jpeg_bytes", &header->jpeg_bytes);
}

static bool read_line(int fd, std::string *line)
{
    line->clear();
    char c = 0;
    while (g_running) {
        ssize_t n = recv(fd, &c, 1, 0);
        if (n == 0) {
            return false;
        }
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            return false;
        }
        if (c == '\n') {
            if (!line->empty() && line->back() == '\r') {
                line->pop_back();
            }
            return true;
        }
        line->push_back(c);
        if (line->size() > 8192) {
            printf("header line is too large\n");
            return false;
        }
    }
    return false;
}

static bool read_exact(int fd, std::vector<unsigned char> *buffer, size_t size)
{
    buffer->assign(size, 0);
    size_t offset = 0;
    while (offset < size && g_running) {
        ssize_t n = recv(fd, buffer->data() + offset, size - offset, 0);
        if (n == 0) {
            return false;
        }
        if (n < 0) {
            if (errno == EINTR) {
                continue;
            }
            return false;
        }
        offset += (size_t)n;
    }
    return offset == size;
}

static bool write_binary_file(const std::string &path, const std::vector<unsigned char> &data)
{
    FILE *fp = fopen(path.c_str(), "wb");
    if (!fp) {
        printf("open %s failed: %s\n", path.c_str(), strerror(errno));
        return false;
    }
    size_t n = fwrite(data.data(), 1, data.size(), fp);
    fclose(fp);
    if (n != data.size()) {
        printf("write %s failed\n", path.c_str());
        return false;
    }
    return true;
}

static bool has_detection_label(const det_object_detect_result_list &results, const char *label)
{
    for (int i = 0; i < results.count; ++i) {
        const char *name = det_coco_cls_to_name(results.results[i].cls_id);
        if (name && strcmp(name, label) == 0) {
            return true;
        }
    }
    return false;
}

static std::string detections_json(const det_object_detect_result_list &results)
{
    std::ostringstream os;
    os << "[";
    int limit = std::min(results.count, 12);
    for (int i = 0; i < limit; ++i) {
        if (i > 0) {
            os << ",";
        }
        const det_object_detect_result &r = results.results[i];
        const char *name = det_coco_cls_to_name(r.cls_id);
        os << "{\"label\":\"" << json_escape(name ? name : "unknown") << "\",";
        os << "\"score\":" << r.prop << ",";
        os << "\"box\":[" << r.box.left << "," << r.box.top << "," << r.box.right << "," << r.box.bottom << "]}";
    }
    os << "]";
    return os.str();
}

// 五个房间的固定顺序（全屋快照按此顺序输出）
static const char *kRooms[] = {"living_room", "bedroom1", "bedroom2", "kitchen", "bathroom"};

static void write_snapshot(const Options &opts, const RuleState &state, int64_t ts_ms)
{
    std::ostringstream os;
    os << "{\"timestamp_ms\":" << ts_ms << ",\"rooms\":{";
    for (size_t i = 0; i < sizeof(kRooms) / sizeof(kRooms[0]); ++i) {
        if (i > 0) {
            os << ",";
        }
        RoomState r;
        std::map<std::string, RoomState>::const_iterator it = state.home_state.find(kRooms[i]);
        if (it != state.home_state.end()) {
            r = it->second;
        }
        os << "\"" << kRooms[i] << "\":{"
           << "\"has_person\":" << (r.has_person ? "true" : "false") << ","
           << "\"has_cat\":" << (r.has_cat ? "true" : "false") << ","
           << "\"has_dog\":" << (r.has_dog ? "true" : "false") << ","
           << "\"fall_like\":" << (r.fall_like ? "true" : "false") << "}";
    }
    os << "}}";

    // 原子写：先写 .tmp，再 rename，避免读方读到半截
    std::string path = opts.snapshot_path;
    std::string tmp = path + ".tmp";
    FILE *fp = fopen(tmp.c_str(), "w");
    if (!fp) {
        printf("write_snapshot open failed: %s\n", strerror(errno));
        return;
    }
    fwrite(os.str().c_str(), 1, os.str().size(), fp);
    fclose(fp);
    if (rename(tmp.c_str(), path.c_str()) != 0) {
        printf("write_snapshot rename failed: %s\n", strerror(errno));
    }
}

static std::string bracelet_json(const BraceletData &bracelet)
{
    std::ostringstream os;
    os << "{\"spo2\":" << bracelet.spo2
       << ",\"heart_rate\":" << bracelet.heart_rate
       << ",\"stress\":" << bracelet.stress
       << ",\"timestamp_ms\":" << bracelet.timestamp_ms << "}";
    return os.str();
}

static void run_action_hook(const Options &opts, const std::string &event_json)
{
    printf("AGENT_EVENT %s\n", event_json.c_str());
    if (opts.action_hook.empty()) {
        return;
    }
    std::string cmd = shell_quote(opts.action_hook) + " " + shell_quote(event_json);
    int rc = system(cmd.c_str());
    if (rc != 0) {
        printf("action hook failed rc=%d cmd=%s\n", rc, opts.action_hook.c_str());
    }
}

static bool should_emit(RuleState *state, const std::string &room, const std::string &event_type, int64_t ts_ms)
{
    std::string key = room + ":" + event_type;
    std::map<std::string, int64_t>::iterator it = state->last_event_ms.find(key);
    if (it != state->last_event_ms.end() && ts_ms - it->second < 60000) {
        return false;
    }
    state->last_event_ms[key] = ts_ms;
    return true;
}

static std::string build_event_json(const std::string &event_type,
                                    const std::string &room,
                                    const std::string &severity,
                                    const std::string &message,
                                    const det_object_detect_result_list &detections,
                                    const BraceletData &bracelet,
                                    int64_t ts_ms)
{
    std::ostringstream os;
    os << "{\"event_type\":\"" << json_escape(event_type) << "\",";
    os << "\"room\":\"" << json_escape(room) << "\",";
    os << "\"severity\":\"" << json_escape(severity) << "\",";
    os << "\"message\":\"" << json_escape(message) << "\",";
    os << "\"timestamp_ms\":" << ts_ms << ",";
    os << "\"detections\":" << detections_json(detections) << ",";
    os << "\"bracelet\":" << bracelet_json(bracelet) << "}";
    return os.str();
}

static bool keypoint_valid(const pose_object_detect_result &result, int index)
{
    return index >= 0 && index < 17 && result.keypoints[index][2] > 0.2f;
}

static bool looks_like_fall(const pose_object_detect_result &result)
{
    int width = result.box.right - result.box.left;
    int height = result.box.bottom - result.box.top;
    if (width <= 0 || height <= 0) {
        return false;
    }

    bool wide_box = width > height * 1.25f;
    bool shoulders = keypoint_valid(result, 5) && keypoint_valid(result, 6);
    bool hips = keypoint_valid(result, 11) && keypoint_valid(result, 12);
    bool knees = keypoint_valid(result, 13) || keypoint_valid(result, 14);
    if (!shoulders || !hips) {
        return wide_box;
    }

    float shoulder_y = (result.keypoints[5][1] + result.keypoints[6][1]) * 0.5f;
    float hip_y = (result.keypoints[11][1] + result.keypoints[12][1]) * 0.5f;
    float shoulder_x = (result.keypoints[5][0] + result.keypoints[6][0]) * 0.5f;
    float hip_x = (result.keypoints[11][0] + result.keypoints[12][0]) * 0.5f;
    bool flat_torso = fabsf(shoulder_y - hip_y) < std::max(20.0f, height * 0.25f);
    bool horizontal_body = fabsf(shoulder_x - hip_x) > width * 0.20f;

    return wide_box || (flat_torso && horizontal_body && knees);
}

static bool any_fall_like_person(const pose_object_detect_result_list &pose_results)
{
    for (int i = 0; i < pose_results.count; ++i) {
        if (looks_like_fall(pose_results.results[i])) {
            return true;
        }
    }
    return false;
}

static BraceletData sample_bracelet(std::mt19937 *rng)
{
    std::uniform_int_distribution<int> spo2_dist(90, 99);
    std::uniform_int_distribution<int> heart_dist(58, 132);
    std::uniform_int_distribution<int> stress_dist(20, 95);
    BraceletData data;
    data.spo2 = spo2_dist(*rng);
    data.heart_rate = heart_dist(*rng);
    data.stress = stress_dist(*rng);
    data.timestamp_ms = now_ms();
    return data;
}

static bool bracelet_abnormal(const BraceletData &data)
{
    return data.spo2 < 92 || data.heart_rate > 120 || data.stress > 85;
}

static void evaluate_rules(const Options &opts,
                           RuleState *state,
                           const FrameHeader &header,
                           const det_object_detect_result_list &det_results,
                           const pose_object_detect_result_list *pose_results)
{
    int64_t ts_ms = header.timestamp_ms > 0 ? header.timestamp_ms : now_ms();
    bool has_person = has_detection_label(det_results, "person");
    bool has_pet = has_detection_label(det_results, "cat") || has_detection_label(det_results, "dog");

    if (header.room == "kitchen" && has_pet && !has_person) {
        state->kitchen_pet_without_person_streak++;
    } else {
        state->kitchen_pet_without_person_streak = 0;
    }

    if (state->kitchen_pet_without_person_streak >= 3 &&
        should_emit(state, header.room, "PET_IN_DANGER_ROOM", ts_ms)) {
        run_action_hook(opts, build_event_json("PET_IN_DANGER_ROOM", header.room, "warning",
            "Pet detected in kitchen without a person nearby.", det_results, state->bracelet, ts_ms));
    }

    if (pose_results) {
        bool fall_like = any_fall_like_person(*pose_results);
        int &fall_streak = state->fall_streak_by_room[header.room];
        fall_streak = fall_like ? fall_streak + 1 : 0;
        if (fall_streak >= 3 && should_emit(state, header.room, "FALL_DETECTED", ts_ms)) {
            run_action_hook(opts, build_event_json("FALL_DETECTED", header.room, "critical",
                "Possible fall detected. Ask whether emergency contact or 120 is needed.",
                det_results, state->bracelet, ts_ms));
        }
    } else {
        state->fall_streak_by_room[header.room] = 0;
    }

    int64_t now = now_ms();
    if (state->last_bracelet_ms == 0 || now - state->last_bracelet_ms >= 2000) {
        static std::random_device rd;
        static std::mt19937 rng(rd());
        state->bracelet = sample_bracelet(&rng);
        state->last_bracelet_ms = now;
        printf("bracelet spo2=%d heart_rate=%d stress=%d\n",
               state->bracelet.spo2, state->bracelet.heart_rate, state->bracelet.stress);
        if (bracelet_abnormal(state->bracelet)) {
            state->health_abnormal_streak++;
        } else {
            state->health_abnormal_streak = 0;
        }
        if (state->health_abnormal_streak >= 2 &&
            should_emit(state, "home", "HEALTH_ABNORMAL", ts_ms)) {
            run_action_hook(opts, build_event_json("HEALTH_ABNORMAL", "home", "warning",
                "Bracelet metrics are abnormal. Adjust hot water, ambient light, and favorite playlist.",
                det_results, state->bracelet, ts_ms));
        }
    }
}

static int create_server_socket(int port)
{
    int server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd < 0) {
        printf("socket failed: %s\n", strerror(errno));
        return -1;
    }

    int opt = 1;
    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons((uint16_t)port);
    if (bind(server_fd, (sockaddr *)&addr, sizeof(addr)) < 0) {
        printf("bind port %d failed: %s\n", port, strerror(errno));
        close(server_fd);
        return -1;
    }
    if (listen(server_fd, 4) < 0) {
        printf("listen failed: %s\n", strerror(errno));
        close(server_fd);
        return -1;
    }
    return server_fd;
}

static int process_frame(const Options &opts,
                         RuleState *state,
                         det_torq_app_context_t *det_ctx,
                         pose_torq_app_context_t *pose_ctx,
                         const FrameHeader &header,
                         const std::vector<unsigned char> &jpeg)
{
    mkdir(opts.tmp_dir.c_str(), 0755);
    std::string frame_path = opts.tmp_dir + "/latest.jpg";
    if (!write_binary_file(frame_path, jpeg)) {
        return -1;
    }

    image_buffer_t image;
    memset(&image, 0, sizeof(image));
    int ret = read_image(frame_path.c_str(), &image);
    if (ret != 0) {
        printf("read_image failed for frame_id=%lld\n", (long long)header.frame_id);
        unlink(frame_path.c_str());
        return -1;
    }

    det_object_detect_result_list det_results;
    memset(&det_results, 0, sizeof(det_results));
    ret = inference_det_yolo11_model(det_ctx, &image, &det_results);
    if (ret != 0) {
        printf("detection inference failed frame_id=%lld ret=%d\n", (long long)header.frame_id, ret);
        if (image.virt_addr) {
            free(image.virt_addr);
        }
        unlink(frame_path.c_str());
        return -1;
    }

    printf("frame=%lld room=%s detections=%d\n",
           (long long)header.frame_id, header.room.c_str(), det_results.count);
    for (int i = 0; i < det_results.count; ++i) {
        det_object_detect_result *r = &det_results.results[i];
        printf("  %s @ (%d %d %d %d) %.3f\n", det_coco_cls_to_name(r->cls_id),
               r->box.left, r->box.top, r->box.right, r->box.bottom, r->prop);
    }

    pose_object_detect_result_list pose_results;
    pose_object_detect_result_list *pose_ptr = NULL;
    memset(&pose_results, 0, sizeof(pose_results));
    if (is_pose_room(header.room) && has_detection_label(det_results, "person")) {
        ret = inference_pose_yolo11_model(pose_ctx, &image, &pose_results);
        if (ret == 0) {
            pose_ptr = &pose_results;
            printf("pose persons=%d\n", pose_results.count);
        } else {
            printf("pose inference failed frame_id=%lld ret=%d\n", (long long)header.frame_id, ret);
        }
    }

    // 更新全屋状态表：本帧检测结果写入对应房间
    RoomState &room_state = state->home_state[header.room];
    room_state.has_person = has_detection_label(det_results, "person");
    room_state.has_cat = has_detection_label(det_results, "cat");
    room_state.has_dog = has_detection_label(det_results, "dog");
    room_state.fall_like = pose_ptr ? any_fall_like_person(*pose_ptr) : false;

    // 输出全屋快照（供云端 Agent 读取）
    int64_t ts_ms = header.timestamp_ms > 0 ? header.timestamp_ms : now_ms();
    write_snapshot(opts, *state, ts_ms);

    // 原有硬编码规则默认关闭，需要时用 --emit-events 打开
    if (opts.emit_events) {
        evaluate_rules(opts, state, header, det_results, pose_ptr);
    }

    if (image.virt_addr) {
        free(image.virt_addr);
    }
    unlink(frame_path.c_str());
    return 0;
}

static void serve_client(int client_fd,
                         const Options &opts,
                         RuleState *state,
                         det_torq_app_context_t *det_ctx,
                         pose_torq_app_context_t *pose_ctx)
{
    while (g_running) {
        std::string line;
        if (!read_line(client_fd, &line)) {
            break;
        }
        FrameHeader header;
        if (!parse_frame_header(line, &header)) {
            printf("bad frame header: %s\n", line.c_str());
            break;
        }
        if (!is_valid_room(header.room)) {
            printf("invalid room: %s\n", header.room.c_str());
            break;
        }
        if (header.jpeg_bytes <= 0 || header.jpeg_bytes > opts.max_jpeg_bytes) {
            printf("invalid jpeg_bytes: %lld\n", (long long)header.jpeg_bytes);
            break;
        }

        std::vector<unsigned char> jpeg;
        if (!read_exact(client_fd, &jpeg, (size_t)header.jpeg_bytes)) {
            printf("client disconnected while reading frame payload\n");
            break;
        }
        process_frame(opts, state, det_ctx, pose_ctx, header, jpeg);
    }
}

int main(int argc, char **argv)
{
    Options opts;
    if (!parse_args(argc, argv, &opts)) {
        return 1;
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);

    printf("agent-butler starting\n");
    printf("det_model=%s pose_model=%s labels=%s port=%d action_hook=%s\n",
           opts.det_model.c_str(), opts.pose_model.c_str(), opts.labels.c_str(),
           opts.port, opts.action_hook.c_str());

    det_torq_app_context_t det_ctx;
    pose_torq_app_context_t pose_ctx;
    memset(&det_ctx, 0, sizeof(det_ctx));
    memset(&pose_ctx, 0, sizeof(pose_ctx));

    set_det_label_path(opts.labels.c_str());
    if (init_det_post_process() != 0) {
        printf("init_det_post_process failed\n");
        return 1;
    }
    if (init_pose_post_process() != 0) {
        printf("init_pose_post_process failed\n");
        deinit_det_post_process();
        return 1;
    }
    if (init_det_yolo11_model(opts.det_model.c_str(), &det_ctx) != 0) {
        printf("init detection model failed\n");
        deinit_pose_post_process();
        deinit_det_post_process();
        return 1;
    }
    if (init_pose_yolo11_model(opts.pose_model.c_str(), &pose_ctx) != 0) {
        printf("init pose model failed\n");
        release_det_yolo11_model(&det_ctx);
        deinit_pose_post_process();
        deinit_det_post_process();
        return 1;
    }

    int server_fd = create_server_socket(opts.port);
    if (server_fd < 0) {
        release_pose_yolo11_model(&pose_ctx);
        release_det_yolo11_model(&det_ctx);
        deinit_pose_post_process();
        deinit_det_post_process();
        return 1;
    }
    printf("listening on 0.0.0.0:%d\n", opts.port);

    RuleState state;
    while (g_running) {
        sockaddr_in client_addr;
        socklen_t client_len = sizeof(client_addr);
        int client_fd = accept(server_fd, (sockaddr *)&client_addr, &client_len);
        if (client_fd < 0) {
            if (errno == EINTR) {
                continue;
            }
            printf("accept failed: %s\n", strerror(errno));
            break;
        }
        char ip[INET_ADDRSTRLEN] = {0};
        inet_ntop(AF_INET, &client_addr.sin_addr, ip, sizeof(ip));
        printf("client connected: %s:%d\n", ip, ntohs(client_addr.sin_port));
        serve_client(client_fd, opts, &state, &det_ctx, &pose_ctx);
        close(client_fd);
        printf("client disconnected\n");
    }

    close(server_fd);
    release_pose_yolo11_model(&pose_ctx);
    release_det_yolo11_model(&det_ctx);
    deinit_pose_post_process();
    deinit_det_post_process();
    printf("agent-butler stopped\n");
    return 0;
}
