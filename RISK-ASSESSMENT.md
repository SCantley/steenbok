# Steenbok Risk Assessment Plan

**Agent:** Steenbok — browser automation for research support

**Primary Use Case:** Research automation for Michelson and Feynman
- Search academic sources (arXiv, PubMed, JSTOR, Google Scholar)
- Extract metadata (DOIs, abstracts, citations)
- Follow source URLs to verify claims
- Screenshot findings
- Navigate to paper pages

**Risk Assessment Required Before Deployment:**

When coding Steenbok, run thorough security review with Opus 4.6 (or equivalent serious model) in Cursor/Antigravity.

**Assessment should cover:**
1. Browser isolation strategy
2. Download handling (quarantine, scanning)
3. Credential access restrictions
4. URL validation/allowlisting
5. JavaScript execution risks
6. Sandbox/container considerations
7. Profile isolation from personal browsing
8. Auto-download prevention
9. Session persistence limits
10. File system access boundaries

**Data Source:**
Analyze `/Users/steve/.openclaw/workspace/logs/web-searches.log` to understand actual search patterns and domains visited.

**Remediation:**
Implement all recommended mitigations before going live.

---

*Created: 2026-02-20*
*Status: Planning phase*
