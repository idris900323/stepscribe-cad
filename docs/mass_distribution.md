# Mass distribution and static joint loads

`05_understanding.md` (section "Mass distribution and static load (estimates)") and `robot.json` carry
estimates from CAD volume and the material or density named for each part. They are not measured values.

## What is computed

- Principal moments, principal axes and radii of gyration about the centre of mass, for every part, every
  link (robots) and the assembly. Only for a valid closed solid with a known material or density; otherwise
  the line says `not computed: <reason>`.
- For a robot: the **static holding torque** (a force for a prismatic joint) of each joint at the pose stored
  in the file, **gravity only**, from the link masses and centres of mass. Label: *static holding torque,
  gravity only, at this pose; not dynamic, not a motor selection*. The value is what the joint must supply to
  hold the pose (minus what gravity applies about the joint's positive axis). A joint is refused when a link
  beyond it has an unknown mass, geometry that is complex or free-form, or is not a closed solid.

## Optional payload

```yaml
payload:
  mass_kg: 2.5
  offset_mm: [0, 0, 150]   # from the last joint's axis point, in the file's axes
```

## Which way gravity points

Gravity points along the opposite of the up axis used for the analysis. The up axis is `+Z` unless you pass
`--up` (for example `--up +Y`) on the command line or set the **Up axis** field of the UI. The designer file
`design_context.yaml` cannot set the up axis: it is an analysis option, not design intent, and it also decides
the front, top and side views, the tipping check and the load paths. The pack section and `robot.json`
(`gravity_direction`, `gravity_note`) state the axis that was used.

## Not included

Support reactions, fastener load share, motor or gearbox sizing and any safety statement.
