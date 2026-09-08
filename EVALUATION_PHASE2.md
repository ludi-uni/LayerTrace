# Phase 2: Five-image evaluation

## Matrix and reproducibility

The five 1254×1254 RGB inputs in `examples/test_pic` were evaluated with 32
colors, simplification epsilon 1.0, underlap 0/1/2/4, and area/containment
ordering: 40 measured runs. Median-cut is deterministic, so no random seed is
used. Every run records its input, dimensions, parameters, UTC timestamp, Git
HEAD state, implementation SHA-256, runtime, and SVG byte size.

The repository has an unborn Git HEAD, so `layertrace_git_head` is recorded as
`null` with `git_head_state: unborn`; the source digest provides the run-specific
implementation identity instead.

## Best observed condition

Visual inspection selected containment ordering with 1px underlap for all five
images. Area ordering was visually almost identical; containment wins only as a
small MAE tie-break at 1px.

| Test | Role | Ordering | Underlap | MAE | White gaps | Shapes | Vertices | Main visible failure |
|---|---|---|---:|---:|---:|---:|---:|---|
| test_1 | simple baseline | containment | 1 | 3.906 | 100183 | 45861 | 308490 | thin hair shading simplifies; minor speckle |
| test_2 | hair complexity | containment | 1 | 3.621 | 93012 | 44595 | 314881 | small locks lose edge fidelity; highlights fragment |
| test_3 | similar adjacent colors | containment | 1 | 3.594 | 75225 | 39668 | 280547 | subtle blue-gray boundaries flatten |
| test_4 | complex background | containment | 1 | 7.710 | 34359 | 15272 | 135284 | plant/shelf detail noise; clothing speckle |
| test_5 | fine highlights | containment | 1 | 4.100 | 83423 | 41668 | thin highlights fragment; shape count stays high |

## Aggregate findings

- Mean MAE by underlap was 10.375, 4.594, 5.682, and 7.820 for 0, 1, 2,
  and 4px respectively. One pixel was the consistent visual and numeric optimum.
- Mean exposed-canvas pixels fell from 524245 at 0px to 77240 at 1px (85.27%).
  Two pixels reduced the metric further to 1701, but MAE rose 23.68% from the
  1px result and visible detail damage/bleed increased. Four pixels was worse.
- Area and containment ordering were nearly tied. At 1px containment lowered
  MAE by 0.007–0.033 on every image, but no clear visual layering difference or
  test_4 foreground/background collapse was found.
- Shape counts were 15272–45861 per run and vertices 124467–380864. Quantized
  anti-aliased edge noise becomes thousands of independent connected regions.
- The main limitation is therefore region/shape explosion, not shared-edge
  cracks or a systematic ordering failure.

## Conclusion

**PROMISING_BUT_LIMITED.** Fixed 1px underlap works across this set and removes
the severe zero-underlap crack pattern without requiring shared topology. The
paint-stack hypothesis remains viable for simple cel-style illustration, while
complex backgrounds and fine highlights expose an impractically large region
count and residual speckle.

The next single variable to evaluate is the existing `min_area` threshold, to
measure whether stronger tiny-region merging can reduce shape explosion without
destroying the highlight-heavy test_5 image.
