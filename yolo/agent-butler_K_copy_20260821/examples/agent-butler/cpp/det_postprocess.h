#ifndef _TORQ_YOLOV8_DEMO_POSTPROCESS_H_
#define _TORQ_YOLOV8_DEMO_POSTPROCESS_H_

#include <stdint.h>
#include <vector>
#include "torq_api.h"
#include "common.h"
#include "image_utils.h"

#define OBJ_NAME_MAX_SIZE 64
#define OBJ_NUMB_MAX_SIZE 128
#define OBJ_CLASS_NUM 80
#define NMS_THRESH 0.45
#define BOX_THRESH 0.25

// class det_torq_app_context_t;

typedef struct {
    image_rect_t box;
    float prop;
    int cls_id;
} det_object_detect_result;

typedef struct {
    int id;
    int count;
    det_object_detect_result results[OBJ_NUMB_MAX_SIZE];
} det_object_detect_result_list;

int init_det_post_process();
void deinit_det_post_process();
void set_det_label_path(const char *path);
const char *det_coco_cls_to_name(int cls_id);
int det_post_process(det_torq_app_context_t *app_ctx, void *outputs, letterbox_t *letter_box, float conf_threshold, float nms_threshold, det_object_detect_result_list *od_results);

void deinit_det_PostProcess();
#endif //_TORQ_YOLOV8_DEMO_POSTPROCESS_H_
