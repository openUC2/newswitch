# How to set up a proper Software Requirements Specification (SRS)

**Purpose of this document:** research findings on the state of the practice for writing an SRS,
used as the methodological basis for `DOC/SRS_V1.md` in the newswitch project.

**Author:** review/planning pass
**Date:** 2026-07-29
**Status:** reference document — not a requirement document itself

---

## 1. Which standard applies

| Standard | Status | Relevance for newswitch |
|---|---|---|
| **ISO/IEC/IEEE 29148:2018** — *Systems and software engineering — Life cycle processes — Requirements engineering* | **Current.** Supersedes IEEE 830-1998, IEEE 1233, IEEE 1362 | **Primary reference.** Defines the SRS outline, the construct of a well-formed requirement, and requirement quality characteristics |
| IEEE 830-1998 | Withdrawn (rolled into 29148) | Still the most-copied outline on the web; use only via 29148 |
| **ISO/IEC 25010:2023** — SQuaRE product quality model | Current (2nd ed.) | **Vocabulary for non-functional requirements.** Nine quality characteristics |
| ISO/IEC 25012 | Current | Data quality model — relevant for image/metadata persistence |
| IEC 62304 | Current | Medical device software lifecycle — **not applicable** unless newswitch is ever used for diagnostics. Worth an explicit "out of scope" statement |

**Conclusion:** structure the newswitch SRS along **ISO/IEC/IEEE 29148:2018 clause 9.6**, and use
**ISO/IEC 25010:2023** as the checklist for the non-functional sections.

---

## 2. The 29148 SRS outline (clause 9.6)

This is the outline the standard prescribes. Section *ordering* is explicitly allowed to be flexible;
the *content* is what must be present.

```
1. Introduction
   1.1 Purpose
   1.2 Scope
   1.3 Product overview
       1.3.1 Product perspective        (context, interfaces to the outside world)
       1.3.2 Product functions          (summary — the "what", not the "how")
       1.3.3 User characteristics       (who operates it, with what skills)
       1.3.4 Limitations                (regulatory, hardware, safety, ...)
   1.4 Definitions, acronyms, abbreviations
2. References
3. Specific requirements
   3.1 External interfaces              (user / hardware / software / communications)
   3.2 Functions                        (the functional core)
   3.3 Usability requirements
   3.4 Performance requirements
   3.5 Logical database requirements    (persisted data, formats, retention)
   3.6 Design constraints               (imposed architecture, languages, standards)
   3.7 Software system attributes       (reliability, security, maintainability, portability, ...)
   3.8 Supporting information
4. Verification                          (mirrors §3 one-to-one: how each requirement is proven)
5. Appendices
   A. Assumptions and dependencies
   B. Acronyms and abbreviations
```

Two structural rules that matter more than the numbering:

1. **Clause 4 (Verification) mirrors clause 3.** For every requirement there must be a stated way to
   prove it. A requirement with no verification method is not a requirement, it is a wish.
2. **§3.6 Design constraints is where an imposed architecture legitimately lives.** This is important
   for newswitch: `basicRequirements.md` mandates the existing architecture, React/Vite/TS, FastAPI,
   rekuest-next, pybind11, CMake, naming conventions. Those are *constraints*, not functions, and the
   standard has a home for them — they do not pollute the functional section.

---

## 3. The construct of a well-formed requirement

29148 defines requirement syntax as five slots:

```
[Condition] [Subject] [Action] [Object] [Constraint of action]
```

Example from the standard:

> *"Upon receiving signal x* **[condition]** *, the system* **[subject]** *shall set* **[action]**
> *the 'signal x received' bit* **[object]** *within 2 seconds* **[constraint of action]** *."*

Practical patterns:

| Pattern | Template |
|---|---|
| Unconditional | The `<subject>` **shall** `<action>` `<object>` `<constraint>`. |
| Conditional | **When** `<trigger>`, the `<subject>` **shall** … |
| State-dependent | **While** `<state>`, the `<subject>` **shall** … |
| Optional feature | **Where** `<feature is present>`, the `<subject>` **shall** … |
| Unwanted behaviour | **If** `<condition>`, **then** the `<subject>` **shall** … |

Modal verb discipline:

- **shall** = binding requirement (the only word that creates an obligation)
- **should** = recommendation / goal
- **may** = permission, optional
- **will** = statement of fact about the environment, not a requirement
- **must** = avoid (reads as legal obligation; ambiguous in translation)

Banned constructions: "user-friendly", "fast", "robust", "efficient", "etc.", "and/or", "as
appropriate", "if possible", "TBD without an owner and a date", and any requirement containing "and"
that actually hides two requirements.

---

## 4. Quality characteristics of individual requirements (29148 clause 5.2.5)

Nine characteristics. Each drafted requirement is checked against all nine:

| # | Characteristic | Test question |
|---|---|---|
| 1 | **Necessary** | If removed, is there a deficiency? If not, delete it |
| 2 | **Appropriate** | Right level of abstraction; no premature implementation detail |
| 3 | **Unambiguous** | Exactly one interpretation, for all readers |
| 4 | **Complete** | Needs no other information to be understood and implemented |
| 5 | **Singular** | States exactly one thing (no hidden "and") |
| 6 | **Feasible** | Achievable within cost, schedule, technology, acceptable risk |
| 7 | **Verifiable** | Provable by inspection, analysis, demonstration or test |
| 8 | **Correct** | Accurately represents the actual stakeholder need |
| 9 | **Conforming** | Follows the approved template/style of this document |

## 5. Quality characteristics of the requirement *set* (clause 5.2.6)

| Characteristic | Test question |
|---|---|
| **Complete** | Are all needs covered? No TBDs left unowned? |
| **Consistent** | No contradictions between requirements |
| **Feasible** | The *set* is achievable together, not just each item alone |
| **Comprehensible** | A reader can grasp the whole without the authors present |
| **Able to be validated** | Stakeholders can confirm the set expresses what they want |

---

## 6. Requirement attributes (metadata per requirement)

The standard expects requirements to carry attributes, not just text. A practical minimum set
(as also used by ReqView's 29148 templates):

| Attribute | Purpose |
|---|---|
| **ID** | Stable, never reused, never renumbered |
| **Text** | The requirement statement |
| **Priority** | e.g. MoSCoW (M / S / C / W) or MVP / v1 / later |
| **Source** | Who/what document raised it (traceability upward) |
| **Rationale** | *Why* — the single most-skipped and most-valuable attribute |
| **Type** | Functional / performance / interface / constraint / quality |
| **Verification method** | Inspection / Analysis / Demonstration / Test |
| **Status** | Draft / reviewed / approved / implemented / verified |
| **Owner** | Who decides on changes |

**Identifier scheme recommendation for newswitch** (stable prefixes by subsystem, so IDs survive
reordering):

```
REQ-<AREA>-<nnn>       e.g. REQ-STG-014  (stage), REQ-CAM-007 (camera)
CON-<AREA>-<nnn>       design constraints
NFR-<CHAR>-<nnn>       non-functional, keyed to ISO 25010 characteristic
```

---

## 7. Verification methods

Every requirement gets exactly one primary method:

| Method | Meaning | Typical newswitch example |
|---|---|---|
| **I — Inspection** | Examine the artefact (code, doc, schema) without executing | Naming conventions, folder layout, logging levels present |
| **A — Analysis** | Modelling, calculation, simulation, reasoning over data | Data-rate budget of 500 MB/s vs. link capacity |
| **D — Demonstration** | Operate the system and observe; no instrumentation | GUI hides a control that the device does not support |
| **T — Test** | Execute with instrumentation against pass/fail criteria | Latency measurement, ring buffer throughput, lock hand-over |

---

## 8. Non-functional taxonomy — ISO/IEC 25010:2023

Nine characteristics in the 2023 edition. Use these as the *section headings* of the non-functional
part so nothing is silently forgotten:

| # | Characteristic | Notes on the 2023 edition |
|---|---|---|
| 1 | **Functional suitability** | completeness, correctness, appropriateness |
| 2 | **Performance efficiency** | time behaviour, resource utilization, capacity |
| 3 | **Compatibility** | co-existence, interoperability |
| 4 | **Interaction capability** | *replaces* "Usability" (2011); adds inclusivity, self-descriptiveness, user engagement |
| 5 | **Reliability** | faultlessness (new), availability, fault tolerance, recoverability |
| 6 | **Security** | confidentiality, integrity, non-repudiation, accountability, authenticity, resistance |
| 7 | **Maintainability** | modularity, reusability, analysability, modifiability, testability |
| 8 | **Flexibility** | *replaces* "Portability" (2011); adaptability, installability, replaceability, **scalability** (new) |
| 9 | **Safety** | **new in 2023**: operational constraint, risk identification, fail-safe, hazard warning, safe integration |

For newswitch, characteristic **9 (Safety)** is not boilerplate: the system drives **lasers and motorised
stages**. Fail-safe behaviour on connection loss belongs here, and `basicRequirements.md` already
states a rule of that kind ("if there is no further user, the microscope shall stop immediately").

---

## 9. Traceability

Minimum viable traceability for a project of this size — two links per requirement:

```
Stakeholder need  ──►  SRS requirement  ──►  Verification case
(basicRequirements.md)   (SRS_V1.md ID)      (test / demo procedure)
                              │
                              └──►  Implementation (module / file)
```

Keep it as a **matrix in the SRS appendix**, not in a separate tool, until the requirement count
exceeds roughly 200. Below that, tooling costs more than it returns.

---

## 10. Process recommendations for this project

1. **Freeze the source documents.** `basicRequirements.md` and `InitReview.md` are inputs; they are
   not edited by the SRS work. Findings that contradict them go into `OpenPoints.md`.
2. **Do not invent answers to open questions.** Mark them ***UNCLEAR*** inline and register them in
   `OpenPoints.md` with an owner. An SRS with visible holes is honest; one with invented content is
   dangerous.
3. **Separate "is" from "shall be".** `InitReview.md` describes the *implemented* Version 1.0. The
   SRS describes the *target*. Where they differ, the delta becomes an MVP task, not a requirement
   rewrite.
4. **Version the SRS, never edit history.** `SRS_V1.md` → `SRS_V2.md`. Changes logged in
   `CHANGELOG_KC.md`.
5. **Requirements are written once, reviewed twice.** One review for content (does this match the
   need?), one for form (the nine characteristics of §4).

---

## 11. Sources

- [ISO/IEC/IEEE 29148:2018 — full standard text (PDF)](https://drkasbokar.com/wp-content/uploads/2024/09/29148-2018-ISOIECIEEE.pdf)
- [ISO/IEC/IEEE 29148 SRS LaTeX template — clause 9.6 outline](https://github.com/wxinix/IEEE-29148-SRS-LaTeX-Template/blob/main/IEEE-29148-2018-SRS-Template.tex)
- [ReqView — ISO/IEC/IEEE 29148 requirements specification templates and attribute set](https://www.reqview.com/doc/iso-iec-ieee-29148-templates/)
- [ReqView — example SRS per 29148](https://www.reqview.com/doc/iso-iec-ieee-29148-srs-example/)
- [Well-Architected Guide — 29148 SRS example template](https://www.well-architected-guide.com/documents/iso-iec-ieee-29148-template/)
- [Modern Requirements — ISO 29148 explained (document family, quality criteria)](https://www.modernrequirements.com/blogs/iso-29148-explained/)
- [Jama Software — writing a system requirements specification](https://www.jamasoftware.com/requirements-management-guide/writing-requirements/system-requirements-specification/)
- [ISO/IEC 25010:2023 — product quality model (official)](https://www.iso.org/standard/78176.html)
- [arc42 quality model — ISO 25010 characteristics](https://quality.arc42.org/standards/iso-25010)
- [Pacific Cert — ISO/IEC 25010:2023 guide, changes vs. 2011](https://blog.pacificcert.com/iso-25010-software-product-quality-model/)
- [jam01/SRS-Template — markdown SRS template (IEEE 830 / 29148 lineage)](https://github.com/jam01/SRS-Template)
