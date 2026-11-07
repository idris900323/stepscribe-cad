"""R0: instance names come from the product, not from assembly-tree occurrence labels like NAUO4."""

from __future__ import annotations


def test_occurrence_labels_are_replaced_by_the_product_name(analyses) -> None:  # type: ignore[no-untyped-def]
    report = analyses("occurrence_label_assembly").report
    assert report.assembly is not None
    names = sorted(i.path.rsplit("/", 1)[-1] for i in report.assembly.instances)
    assert names == ["Holder", "LINK3", "LINK6"], names


def test_a_meaningful_instance_label_is_kept(analyses) -> None:  # type: ignore[no-untyped-def]
    """Only occurrence-style labels are replaced: 'Holder' (an instance of LINK2) stays."""
    report = analyses("occurrence_label_assembly").report
    assert report.assembly is not None
    assert any(i.path.endswith("/Holder") for i in report.assembly.instances)
