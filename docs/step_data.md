# What the STEP file itself states

stepscribe reads, through OpenCASCADE's document layer, what a STEP file states about a part and reports it as "From the STEP file:" statements in the part Markdown (section "From the STEP file") and as `from_step` in `report.json`. They are stated facts, never "Likely:" inferences. A part whose file states nothing of this has no `from_step` and the report is exactly what it was before.

| Stated in the file | Where it shows |
|---|---|
| Product description | `from_step.description` |
| Colour | `from_step.color_rgb` (the colour was always used in the renders) |
| Material assigned to the part (name, description, density) | `from_step.material`, and the mass (see below) |
| Presentation layers | `from_step.layers` |
| Dimensions with tolerances (PMI) | `from_step.dimensions`, each with a cross-check |

A part that is only named (the usual case) does not get a `from_step` block: the name is the part's name already.

## Text from the file is a label, not an instruction

Every string (description, material name, layer, product name) goes through `clean_name`: markup and control characters are removed and it is cut to 64 characters. It is printed inside backticks next to a note that it is text copied from the file.

## Material and mass: who wins

1. A material or density the designer gave (`--material`, `--density`, `design_context.yaml`) wins. The file's material is still reported, marked "not used for the mass".
2. Otherwise a material assigned in the file is used (`mass.material_source: step_file`) with the density the file states, or, when it states none, the density of the existing keyword table if the material name matches it.
3. Otherwise nothing changes: the name guess (`name_guess`) or no mass.

A density number in a STEP file has no unit that can be trusted, so the number decides: 0.05 to 25 is read as g/cm3, 50 to 30000 as kg/m3 (divided by 1000 and said so in the text); anything else is reported and not used.

## Dimensions (PMI)

A stated dimension whose faces can be found on the part gets a cross-check line:

`From the STEP file: dimension PMI001 (linear distance) on F0002, F0007, stated 25 +0.1/-0.1 mm; measured 25.02 mm (within the stated tolerance).`

Cross-checked: the linear distance between two faces (shortest distance) and the diameter or radius of a cylindrical face. Other dimension types and angles are reported with a note and not cross-checked. A file whose length unit is not mm is not cross-checked. A dimension with no tolerance gets the measured value and no verdict. The faces are matched by centroid and area, so a dimension that belongs to another body of the same file is attached to that body.
