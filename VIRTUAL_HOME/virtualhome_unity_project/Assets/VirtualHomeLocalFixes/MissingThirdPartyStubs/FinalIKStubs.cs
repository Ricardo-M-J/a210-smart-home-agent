using System;
using UnityEngine;

namespace RootMotion.FinalIK
{
    public enum FullBodyBipedEffector
    {
        Body,
        LeftShoulder,
        RightShoulder,
        LeftThigh,
        RightThigh,
        LeftHand,
        RightHand,
        LeftFoot,
        RightFoot,
    }

    [Serializable]
    public class IKEffector
    {
        public Transform target;
        public float positionWeight;
        public float rotationWeight;
        public float maintainRelativePositionWeight;
    }

    [Serializable]
    public class FBIKChain
    {
        public BendConstraint bendConstraint = new BendConstraint();
    }

    [Serializable]
    public class BendConstraint
    {
        public Transform bendGoal;
        public float weight;
    }

    [Serializable]
    public class IKSolverFullBodyBiped
    {
        public FBIKChain leftArmChain = new FBIKChain();
        public FBIKChain rightArmChain = new FBIKChain();

        readonly IKEffector body = new IKEffector();
        readonly IKEffector leftShoulder = new IKEffector();
        readonly IKEffector rightShoulder = new IKEffector();
        readonly IKEffector leftThigh = new IKEffector();
        readonly IKEffector rightThigh = new IKEffector();
        readonly IKEffector leftHand = new IKEffector();
        readonly IKEffector rightHand = new IKEffector();

        public IKEffector GetEffector(FullBodyBipedEffector effector)
        {
            switch (effector)
            {
                case FullBodyBipedEffector.LeftShoulder:
                    return leftShoulder;
                case FullBodyBipedEffector.RightShoulder:
                    return rightShoulder;
                case FullBodyBipedEffector.LeftThigh:
                    return leftThigh;
                case FullBodyBipedEffector.RightThigh:
                    return rightThigh;
                case FullBodyBipedEffector.LeftHand:
                    return leftHand;
                case FullBodyBipedEffector.RightHand:
                    return rightHand;
                default:
                    return body;
            }
        }
    }

    [Serializable]
    public class BipedReferences
    {
        public Transform leftThigh;
        public Transform rightThigh;
        public Transform leftUpperArm;
        public Transform rightUpperArm;
        public Transform[] spine = Array.Empty<Transform>();
    }

    public class FullBodyBipedIK : MonoBehaviour
    {
        public BipedReferences references = new BipedReferences();
        public IKSolverFullBodyBiped solver = new IKSolverFullBodyBiped();

        void Awake()
        {
            EnsureReferences();
        }

        void Reset()
        {
            EnsureReferences();
        }

        void EnsureReferences()
        {
            if (references == null)
            {
                references = new BipedReferences();
            }

            if (references.leftThigh == null)
            {
                references.leftThigh = transform;
            }

            if (references.rightThigh == null)
            {
                references.rightThigh = transform;
            }

            if (references.leftUpperArm == null)
            {
                references.leftUpperArm = transform;
            }

            if (references.rightUpperArm == null)
            {
                references.rightUpperArm = transform;
            }

            if (references.spine == null || references.spine.Length == 0 || references.spine[0] == null)
            {
                references.spine = new[] { transform };
            }
        }
    }

    public class InteractionSystem : MonoBehaviour
    {
        public float speed = 1.0f;
        public bool inInteraction { get; private set; }

        public void StartInteraction(FullBodyBipedEffector effector, InteractionObject interactionObject, bool interrupt)
        {
            inInteraction = false;
            if (interactionObject != null)
            {
                interactionObject.TriggerMessages();
            }
        }
    }

    public class InteractionObject : MonoBehaviour
    {
        public WeightCurve[] weightCurves = CreateDefaultWeightCurves();
        public Multiplier[] multipliers = Array.Empty<Multiplier>();
        public InteractionEvent[] events = CreateDefaultEvents();

        public void Initiate()
        {
            EnsureDefaults();
        }

        public void TriggerMessages()
        {
            EnsureDefaults();
            foreach (var interactionEvent in events)
            {
                if (interactionEvent?.messages == null)
                {
                    continue;
                }

                foreach (var message in interactionEvent.messages)
                {
                    if (message?.recipient != null && !string.IsNullOrEmpty(message.function))
                    {
                        message.recipient.SendMessage(message.function, SendMessageOptions.DontRequireReceiver);
                    }
                }
            }
        }

        void Reset()
        {
            EnsureDefaults();
        }

        void EnsureDefaults()
        {
            if (weightCurves == null || weightCurves.Length < 2)
            {
                weightCurves = CreateDefaultWeightCurves();
            }

            if (multipliers == null)
            {
                multipliers = Array.Empty<Multiplier>();
            }

            if (events == null || events.Length == 0)
            {
                events = CreateDefaultEvents();
            }
        }

        static WeightCurve[] CreateDefaultWeightCurves()
        {
            return new[]
            {
                new WeightCurve(),
                new WeightCurve(),
            };
        }

        static InteractionEvent[] CreateDefaultEvents()
        {
            return new[]
            {
                new InteractionEvent
                {
                    messages = new[] { new Message() },
                    animations = Array.Empty<AnimatorEvent>(),
                },
            };
        }

        [Serializable]
        public class WeightCurve
        {
            public int type;
            public AnimationCurve curve = AnimationCurve.Linear(0.0f, 1.0f, 1.0f, 1.0f);
        }

        [Serializable]
        public class Multiplier
        {
            public AnimationCurve curve = AnimationCurve.Linear(0.0f, 1.0f, 1.0f, 1.0f);
            public float multiplier = 1.0f;
            public int result;
        }

        [Serializable]
        public class InteractionEvent
        {
            public float time;
            public bool pickUp = true;
            public Message[] messages = new[] { new Message() };
            public AnimatorEvent[] animations = Array.Empty<AnimatorEvent>();
        }

        [Serializable]
        public class Message
        {
            public GameObject recipient;
            public string function;
        }

        [Serializable]
        public class AnimatorEvent
        {
        }
    }
}
