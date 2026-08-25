# Unity Safe Mode: Missing Third-Party Dependencies

## Current Cause

When opening `virtualhome_unity_project`, Unity enters Safe Mode because the
project references third-party namespaces that are not present in the downloaded
source tree:

```text
RootMotion.FinalIK
DunGen
```

Typical errors in `Editor.log`:

```text
error CS0246: The type or namespace name 'RootMotion' could not be found
error CS0246: The type or namespace name 'DunGen' could not be found
error CS0246: The type or namespace name 'FullBodyBipedIK' could not be found
error CS0246: The type or namespace name 'InteractionSystem' could not be found
```

This is not caused by the Python scripts. It is a Unity source dependency
problem.

## Temporary Local Fix Already Added

A local compile-time compatibility layer has been added here:

```text
virtualhome_unity_project/Assets/VirtualHomeLocalFixes/MissingThirdPartyStubs/
```

It defines minimal replacements for:

```text
RootMotion.FinalIK.FullBodyBipedIK
RootMotion.FinalIK.InteractionSystem
RootMotion.FinalIK.InteractionObject
RootMotion.FinalIK.FullBodyBipedEffector
DunGen.RuntimeDungeon
DunGen.DungeonGenerator
DunGen.CoroutineHelper
```

This should let Unity compile far enough to leave Safe Mode and open the scene
for viewing, dragging objects, camera placement, and basic VirtualHome-side
editing.

## Important Limitation

The local stubs do not implement real Final IK or DunGen behavior.

Affected features:

```text
real hand IK
precise grab/put/drop interaction
body IK while sitting or opening doors
DunGen runtime procedural house generation
```

For the smart-home visual-agent showcase, this is acceptable for scene viewing,
camera placement, lighting control interface design, and demo panel integration.
For fully natural character-object interaction inside Unity, import the real
packages.

The DunGen stubs intentionally use the original scene GUIDs:

```text
RuntimeDungeon.cs.meta   510e6e61902a25245878393904bd5d0d
CoroutineHelper.cs.meta  8d5e84273fce13e41969baa0fb65e754
```

This reconnects `Home_Procedural_Generation` and `DunGen Coroutine Helper`
instead of leaving them as `Missing Mono Script`.

## What To Do In Unity

1. Stay in Safe Mode.
2. Wait for Unity to detect the new scripts, or click `Retry` / `Reimport`.
3. If the compile errors disappear, click `Exit Safe Mode`.
4. Open:

```text
Assets/Story Generator/Scene/Scene_0.unity
```

5. Press `Play` only after the Console no longer shows red compile errors.

## If You Later Import Real Packages

Before importing the real `Final IK` or `DunGen` packages, delete:

```text
Assets/VirtualHomeLocalFixes/MissingThirdPartyStubs
```

Otherwise Unity will report duplicate type definition errors.

## Correct Long-Term Fix

Install/import the missing packages that the original Unity project expected:

```text
RootMotion Final IK
DunGen
```

Because these are third-party Unity assets, they are often omitted from public
GitHub source archives for licensing reasons. That is why the prebuilt
`windows_exec` simulator can run while the downloaded Unity source project
cannot compile immediately.
