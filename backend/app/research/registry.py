"""Jurisdiction-aware registry of responsible authorities and official sources.

Authority mapping is curated and must be confirmed by a regulatory specialist
for each product. Reachability of each source URL is checked by the app and
shown on the Regulatory page ("last successful check"). Add regions by adding
rows here; the rest of the module is data-driven.
"""

from __future__ import annotations

import sqlite3

# scope: human_drug | human_biologic | vet_drug | vet_biologic
# access: api (structured search), index_page (link scan of an official page), manual_only
SOURCES = [
    # ------------------------------------------------------------- United States
    ("US", "FDA Center for Veterinary Medicine (CVM)", "vet_drug", "FDA guidance documents (CVM)", "https://www.fda.gov/regulatory-information/search-fda-guidance-documents", "api", "en",
     "New animal drugs, including many therapeutic proteins and monoclonal antibodies for animals, are regulated by FDA CVM. Connector: fda_guidance (center = Veterinary)."),
    ("US", "FDA Center for Veterinary Medicine (CVM)", "vet_biologic", "FDA guidance documents (CVM)", "https://www.fda.gov/regulatory-information/search-fda-guidance-documents", "api", "en",
     "Some veterinary antibodies are FDA CVM 'new animal drugs'; jurisdiction vs USDA depends on mechanism and claims (FDA-USDA jurisdiction determination)."),
    ("US", "USDA APHIS Center for Veterinary Biologics (CVB)", "vet_biologic", "USDA APHIS CVB (notices via Federal Register)", "https://www.federalregister.gov/agencies/animal-and-plant-health-inspection-service", "api", "en",
     "Veterinary biologics acting through the immune system (e.g., vaccines, some immunotherapeutics) are licensed by USDA CVB under the Virus-Serum-Toxin Act. The APHIS website blocks automated retrieval (HTTP 403), so CVB notices are searched via the Federal Register API and CVB guidance must be checked manually."),
    ("US", "Federal Register (FDA and APHIS rules and notices)", "vet_drug", "Federal Register API", "https://www.federalregister.gov/api/v1", "api", "en", "Binding rules, proposed rules and notices."),
    ("US", "FDA Center for Drug Evaluation and Research (CDER)", "human_drug", "FDA guidance documents (CDER)", "https://www.fda.gov/regulatory-information/search-fda-guidance-documents", "api", "en",
     "Human small molecules and most therapeutic biologics including monoclonal antibodies."),
    ("US", "FDA Center for Biologics Evaluation and Research (CBER)", "human_biologic", "FDA guidance documents (CBER)", "https://www.fda.gov/regulatory-information/search-fda-guidance-documents", "api", "en",
     "Vaccines, blood products, cell and gene therapies. Therapeutic mAbs are generally CDER."),
    # ------------------------------------------------------------- European Union
    ("EU", "European Medicines Agency - CVMP", "vet_drug", "EMA documents catalogue (veterinary guidelines)", "https://www.ema.europa.eu/en/documents/report/documents-output-json-report_en.json", "api", "en",
     "Centralised veterinary authorisations under Regulation (EU) 2019/6; national competent authorities handle national procedures."),
    ("EU", "European Medicines Agency - CVMP", "vet_biologic", "EMA documents catalogue (veterinary guidelines)", "https://www.ema.europa.eu/en/documents/report/documents-output-json-report_en.json", "api", "en",
     "Biotechnology-derived veterinary medicines (incl. mAbs) are in the centralised procedure's scope."),
    ("EU", "European Medicines Agency - CHMP", "human_drug", "EMA documents catalogue (human guidelines)", "https://www.ema.europa.eu/en/documents/report/documents-output-json-report_en.json", "api", "en", "Human medicines; national authorities for national routes."),
    ("EU", "European Medicines Agency - CHMP", "human_biologic", "EMA documents catalogue (human guidelines)", "https://www.ema.europa.eu/en/documents/report/documents-output-json-report_en.json", "api", "en", "Biotech human medicines are centrally authorised."),
    # ------------------------------------------------------------- China
    ("CN", "Ministry of Agriculture and Rural Affairs (MARA), Bureau of Animal Husbandry and Veterinary; China Institute of Veterinary Drug Control (IVDC)", "vet_drug",
     "MARA notices (通知公告)", "https://www.moa.gov.cn/gk/tzgg_1/", "index_page", "zh",
     "Veterinary drugs (兽药), including veterinary biologics, are regulated by MARA with IVDC technical review - not by NMPA."),
    ("CN", "Ministry of Agriculture and Rural Affairs (MARA) / IVDC", "vet_biologic", "MARA notices (通知公告)", "https://www.moa.gov.cn/gk/tzgg_1/", "index_page", "zh",
     "New veterinary biologics registration (新兽药注册) via MARA; IVDC site (www.ivdc.org.cn) times out intermittently."),
    ("CN", "National Medical Products Administration (NMPA) / Center for Drug Evaluation (CDE)", "human_drug", "NMPA website", "https://www.nmpa.gov.cn/", "manual_only", "zh",
     "Human drugs and biologics. The site rejects automated requests (HTTP 412); check manually."),
    ("CN", "National Medical Products Administration (NMPA) / CDE", "human_biologic", "NMPA website", "https://www.nmpa.gov.cn/", "manual_only", "zh", "Manual check required."),
    # ------------------------------------------------------------- Japan
    ("JP", "Ministry of Agriculture, Forestry and Fisheries (MAFF) - National Veterinary Assay Laboratory (NVAL)", "vet_drug", "NVAL home (動物医薬品検査所)", "https://www.maff.go.jp/nval/", "index_page", "ja",
     "Veterinary medicinal products (動物用医薬品) are approved by MAFF with NVAL review."),
    ("JP", "MAFF - NVAL", "vet_biologic", "NVAL home (動物医薬品検査所)", "https://www.maff.go.jp/nval/", "index_page", "ja", "Veterinary biologics (動物用生物学的製剤) also under MAFF/NVAL."),
    ("JP", "Ministry of Health, Labour and Welfare (MHLW) / PMDA", "human_drug", "PMDA English site", "https://www.pmda.go.jp/english/", "index_page", "en", "Human drugs and biologics."),
    ("JP", "MHLW / PMDA", "human_biologic", "PMDA English site", "https://www.pmda.go.jp/english/", "index_page", "en", "Human biologics."),
    # ------------------------------------------------------------- South Korea
    ("KR", "Animal and Plant Quarantine Agency (APQA, under MAFRA)", "vet_drug", "APQA home (농림축산검역본부)", "https://www.apqa.go.kr/", "index_page", "ko",
     "Veterinary medicinal products (동물용의약품) licensing; qia.go.kr redirects to apqa.go.kr."),
    ("KR", "Animal and Plant Quarantine Agency (APQA, under MAFRA)", "vet_biologic", "APQA home (농림축산검역본부)", "https://www.apqa.go.kr/", "index_page", "ko", "Veterinary biologics including vaccines."),
    ("KR", "Ministry of Food and Drug Safety (MFDS)", "human_drug", "MFDS guidelines (English)", "https://www.mfds.go.kr/eng/brd/m_1127/list.do", "index_page", "en", "Human drugs and biologics."),
    ("KR", "Ministry of Food and Drug Safety (MFDS)", "human_biologic", "MFDS guidelines (English)", "https://www.mfds.go.kr/eng/brd/m_1127/list.do", "index_page", "en", "Human biologics."),
]

JURISDICTIONS = ["US", "EU", "CN", "JP", "KR"]


def seed(conn: sqlite3.Connection) -> int:
    n = 0
    for jur, auth, scope, name, url, access, lang, notes in SOURCES:
        n += conn.execute(
            "INSERT INTO regulatory_sources (jurisdiction, authority, scope, name, url, access, language, notes) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(jurisdiction, scope, url) DO UPDATE SET authority=excluded.authority, name=excluded.name, access=excluded.access, notes=excluded.notes",
            (jur, auth, scope, name, url, access, lang, notes),
        ).rowcount
    return n


def scopes_for(program: dict) -> list[str]:
    vet = program.get("use_type") == "veterinary"
    bio = program.get("molecule_category") == "biologic"
    if program.get("use_type") == "unknown":
        return ["vet_drug", "vet_biologic", "human_drug", "human_biologic"] if bio else ["vet_drug", "human_drug"]
    if vet:
        return ["vet_drug", "vet_biologic"] if bio else ["vet_drug"]
    return ["human_biologic", "human_drug"] if bio else ["human_drug"]
