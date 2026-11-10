"""Render tailored résumé content as Markdown, DOCX and tailoring notes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt

from .ai import describe_ai


def _joined(*parts: Any) -> str:
    return " | ".join(str(part).strip() for part in parts if str(part or "").strip())


def contact_lines(identity: dict[str, Any]) -> list[str]:
    """The contact lines under the name; empty fields are left out."""
    lines = [
        _joined(identity.get("location"), identity.get("phone"), identity.get("email")),
        _joined(identity.get("linkedin"), identity.get("github"), identity.get("website")),
    ]
    return [line for line in lines if line]


def experience_heading(experience: dict[str, Any]) -> str:
    return _joined(experience.get("role"), experience.get("company"), experience.get("dates"))


def skill_line(skill: dict[str, Any]) -> tuple[str, str]:
    """(category, text); the category may be empty."""
    return str(skill.get("category") or "").strip(), str(skill.get("text") or "").strip()


def project_heading(project: dict[str, Any]) -> tuple[str, str]:
    """(name, the line under it); the line may be empty."""
    return str(project.get("name") or "").strip(), _joined(project.get("details"), project.get("dates"))


# Two trailing spaces: a Markdown line break, so consecutive lines don't run together as one paragraph.
_BREAK = "  "


def _paragraph(lines: list[str]) -> list[str]:
    """One Markdown paragraph that keeps each of `lines` on its own line, then a blank line."""
    lines = [line for line in lines if line]
    return [*(line + _BREAK for line in lines[:-1]), *lines[-1:], ""] if lines else []


def _bullets(texts: list[str]) -> list[str]:
    """A Markdown list, then a blank line. The caller's previous block already ended with one."""
    return [*(f"- {text}" for text in texts), ""] if texts else []


def _bullet_texts(entry: dict[str, Any]) -> list[str]:
    return [bullet["text"] for bullet in entry.get("bullets") or []]


def markdown_resume(content: dict[str, Any]) -> str:
    """Standard Markdown: a blank line around every heading, paragraph and list, so GitHub, pandoc
    and other converters all render the same lines and bullets."""
    identity = content["identity"]
    lines = [f"# {identity['name']}", ""]
    if identity.get("headline"):
        lines += [f"**{identity['headline']}**", ""]
    lines += _paragraph(contact_lines(identity))
    lines += ["## PROFESSIONAL SUMMARY", "", content["summary"], ""]

    if content.get("technical_skills"):
        lines += ["## SKILLS", ""]
        # Categorised skills are lines of one paragraph, uncategorised ones a list; keep their order.
        labelled: list[str] = []
        plain: list[str] = []
        for skill in content["technical_skills"]:
            category, text = skill_line(skill)
            if category:
                lines += _bullets(plain)
                plain = []
                labelled.append(f"**{category}:** {text}")
            else:
                lines += _paragraph(labelled)
                labelled = []
                plain.append(text)
        lines += _paragraph(labelled) + _bullets(plain)

    if content.get("experience"):
        lines += ["## PROFESSIONAL EXPERIENCE", ""]
        for experience in content["experience"]:
            lines += [f"**{experience_heading(experience)}**", ""]
            lines += _bullets(_bullet_texts(experience))

    if content.get("projects"):
        lines += ["## PROJECTS", ""]
        for project in content["projects"]:
            name, where = project_heading(project)
            lines += _paragraph([f"**{name}**", where])
            lines += _bullets(_bullet_texts(project))

    if content.get("education"):
        lines += ["## EDUCATION", ""]
        for education in content["education"]:
            where = _joined(education.get("school"), education.get("dates"))
            lines += _paragraph([f"**{education['program']}**", where])
            lines += _bullets(_bullet_texts(education))

    if content.get("certifications"):
        lines += ["## CERTIFICATIONS", ""]
        primary = content["certifications"][:4]
        additional = content["certifications"][4:]
        lines += _bullets([cert["text"] for cert in primary])
        if additional:
            lines += ["Additional certificates: " + "; ".join(c["text"] for c in additional), ""]

    return "\n".join(lines).rstrip() + "\n"


def _set_cellless_doc_defaults(document: Document) -> None:
    section = document.sections[0]
    section.top_margin = Inches(0.45)
    section.bottom_margin = Inches(0.45)
    section.left_margin = Inches(0.55)
    section.right_margin = Inches(0.55)

    styles = document.styles
    normal = styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(9.5)
    normal.paragraph_format.space_after = Pt(2)
    normal.paragraph_format.line_spacing = 1.0

    if "List Bullet" in styles:
        bullet = styles["List Bullet"]
        bullet.font.name = "Arial"
        bullet.font.size = Pt(9.4)
        bullet.paragraph_format.space_after = Pt(1)
        bullet.paragraph_format.left_indent = Inches(0.18)
        bullet.paragraph_format.first_line_indent = Inches(-0.12)


def _section_heading(document: Document, text: str) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(5)
    paragraph.paragraph_format.space_after = Pt(2)
    run = paragraph.add_run(text)
    run.bold = True
    run.font.name = "Arial"
    run.font.size = Pt(10.5)


def _bullet(document: Document, text: str) -> None:
    paragraph = document.add_paragraph(style="List Bullet")
    paragraph.add_run(text)


def docx_resume(content: dict[str, Any], path: Path) -> None:
    document = Document()
    _set_cellless_doc_defaults(document)
    identity = content["identity"]

    p = document.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(1)
    r = p.add_run(identity["name"])
    r.bold = True
    r.font.name = "Arial"
    r.font.size = Pt(16)

    if identity.get("headline"):
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(1)
        r = p.add_run(identity["headline"])
        r.bold = True
        r.font.name = "Arial"
        r.font.size = Pt(10.5)

    for line in contact_lines(identity):
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(line)
        r.font.name = "Arial"
        r.font.size = Pt(8.8)

    _section_heading(document, "PROFESSIONAL SUMMARY")
    document.add_paragraph(content["summary"])

    if content.get("technical_skills"):
        _section_heading(document, "SKILLS")
        for skill in content["technical_skills"]:
            category, text = skill_line(skill)
            if not category:
                _bullet(document, text)
                continue
            p = document.add_paragraph()
            p.paragraph_format.space_after = Pt(1)
            r = p.add_run(f"{category}: ")
            r.bold = True
            p.add_run(text)

    if content.get("experience"):
        _section_heading(document, "PROFESSIONAL EXPERIENCE")
        for experience in content["experience"]:
            p = document.add_paragraph()
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(1)
            r = p.add_run(experience_heading(experience))
            r.bold = True
            for bullet in experience.get("bullets", []):
                _bullet(document, bullet["text"])

    if content.get("projects"):
        _section_heading(document, "PROJECTS")
        for project in content["projects"]:
            name, where = project_heading(project)
            p = document.add_paragraph()
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(name)
            r.bold = True
            if where:
                document.add_paragraph(where)
            for bullet in project.get("bullets", []):
                _bullet(document, bullet["text"])

    if content.get("education"):
        _section_heading(document, "EDUCATION")
        for education in content["education"]:
            p = document.add_paragraph()
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(education["program"])
            r.bold = True
            if where := _joined(education.get("school"), education.get("dates")):
                document.add_paragraph(where)
            for bullet in education.get("bullets", []):
                _bullet(document, bullet["text"])

    if content.get("certifications"):
        _section_heading(document, "CERTIFICATIONS")
        primary = content["certifications"][:4]
        additional = content["certifications"][4:]
        for cert in primary:
            _bullet(document, cert["text"])
        if additional:
            document.add_paragraph("Additional certificates: " + "; ".join(c["text"] for c in additional))

    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path)


def tailoring_notes(
    job: dict[str, Any],
    scored: dict[str, Any],
    master_version: str,
    ai_audit: dict[str, Any],
) -> str:
    def values(key: str) -> str:
        items = scored.get(key, [])
        return ", ".join(items) if items else "None"

    return "\n".join(
        [
            "# Tailoring Notes",
            "",
            f"- Master resume version: {master_version}",
            f"- Job: {job.get('title', '')} — {job.get('company', '')}",
            f"- Match score at generation: {scored.get('score', 0)}%",
            f"- Emphasized matched skills: {values('matched_skills')}",
            f"- Missing core skills NOT added to resume: {values('missing_skills')}",
            f"- Optional gaps NOT added to resume: {values('optional_missing_skills')}",
            f"- AI wording: {describe_ai(ai_audit.get('status', ''), ai_audit.get('model', ''))}",
            "",
            "Policy: deterministic selection happens first. AI may improve wording only inside the "
            "master-resume factual whitelist. Rule checks and a second AI factual-verification pass "
            "must succeed before AI wording is accepted; otherwise the deterministic resume is used.",
            "",
        ]
    )
