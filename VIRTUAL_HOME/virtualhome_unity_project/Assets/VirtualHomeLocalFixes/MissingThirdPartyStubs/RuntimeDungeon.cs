using System;
using UnityEngine;

namespace DunGen
{
    public class RuntimeDungeon : MonoBehaviour
    {
        public DungeonGenerator Generator = new DungeonGenerator();
        public bool GenerateOnStart;
        public GameObject Root;

        void Start()
        {
            if (GenerateOnStart)
            {
                Generator.Generate();
            }
        }
    }

    [Serializable]
    public class DungeonGenerator
    {
        public bool allowImmediateRepeats;
        public int Seed;
        public bool ShouldRandomizeSeed;
        public int MaxAttemptCount = 1000;
        public bool UseMaximumPairingAttempts;
        public int MaxPairingAttempts = 5;
        public bool IgnoreSpriteBounds;
        public int UpDirection = 2;
        public bool OverrideRepeatMode;
        public int RepeatMode;
        public bool OverrideAllowTileRotation;
        public bool AllowTileRotation;
        public bool DebugRender;
        public float LengthMultiplier = 1.0f;
        public bool PlaceTileTriggers = true;
        public int TileTriggerLayer = 2;
        public bool GenerateAsynchronously;
        public float MaxAsyncFrameMilliseconds = 50.0f;
        public float PauseBetweenRooms = 0.47f;
        public bool RestrictDungeonToBounds;
        public Bounds TilePlacementBounds = new Bounds(Vector3.zero, Vector3.one * 10.0f);
        public float OverlapThreshold = 0.01f;
        public float Padding;
        public bool DisallowOverhangs;
        public GameObject Root;
        public UnityEngine.Object DungeonFlow;
        public int fileVersion = 1;

        public void Generate()
        {
            Debug.LogWarning("DunGen is not installed. Runtime dungeon generation is skipped by the local stub.");
        }
    }
}
