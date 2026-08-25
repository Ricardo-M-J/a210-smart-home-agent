# Missing Third-Party Dependency Stubs

These scripts are local compile-time shims for opening the VirtualHome Unity
source project when the original third-party Unity assets are not installed.

Missing dependencies seen in `Editor.log`:

- `RootMotion.FinalIK`
- `DunGen`

The stubs are intentionally minimal. They let Unity compile and open the scene,
but they do not implement real Final IK hand/body interaction or DunGen runtime
floor-plan generation.

The DunGen stubs intentionally reuse GUIDs referenced by the original scenes:

```text
RuntimeDungeon.cs.meta   510e6e61902a25245878393904bd5d0d
CoroutineHelper.cs.meta  8d5e84273fce13e41969baa0fb65e754
```

This reconnects `Home_Procedural_Generation` and `DunGen Coroutine Helper`
instead of leaving them as `Missing Mono Script`.

When the real packages are imported, delete this folder first to avoid duplicate
type definitions:

```text
Assets/VirtualHomeLocalFixes/MissingThirdPartyStubs
```
