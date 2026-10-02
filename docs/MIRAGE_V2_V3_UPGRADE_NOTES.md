# MIRAGE V2/V3 Upgrade Notes

## V2 closure target

V2 should focus on proof quality, not feature breadth:

1. clean package hygiene,
2. production fail-closed boundaries,
3. canonical receiver clarity,
4. signed leak evidence,
5. evidence-chain verification,
6. optional AGON event handoff scaffold.

No DOCX/PDF/SIEM/multi-tenant expansion should enter V2 unless the evidence chain is already green.

## "Benden olsun" recommendation: Evidence Capsule

The strongest V3-level differentiator is not PDF/DOCX support. It is an **Evidence Capsule**.

An Evidence Capsule is a single exportable package for one leak incident:

```txt
incident.json
beacon-chain.json
verify-result.json
honeytoken-file-sha256.txt
passive-only-proof.json
operator-notes.md
README-for-auditor.md
```

Purpose:

- compress all leak evidence into one reviewable bundle,
- let an auditor/customer verify the beacon chain without trusting the dashboard,
- support legal/compliance review without claiming formal certification,
- align MIRAGE with AGON/HUQAN's evidence-first architecture.

Suggested V3 positioning:

> MIRAGE does not only detect that a decoy file was opened; it produces a portable, verifiable evidence capsule for the incident.

## V3 backlog order

1. Evidence Capsule export.
2. AGON event handoff with signed event payload.
3. SIEM/Slack/Teams forwarding.
4. DOCX honeytoken support.
5. Prompt-layer canary.
6. Multi-tenant workspace.
7. Geo-IP enrichment.
8. PDF support last, because viewer behavior is inconsistent.
