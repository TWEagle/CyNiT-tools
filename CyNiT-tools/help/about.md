# CyNiT Certificate / CSR Decoder

Deze tool is gemaakt om X.509 certificaten en CSRs snel te kunnen analyseren.

## Functionaliteit

- Ondersteuning voor certificaten en CSRs in PEM en DER
- GUI én Web interface
- Overzicht van:
  - Certificate Subject
  - Certificate Issuer
  - Certificate Properties
- Export naar:
  - JSON
  - CSV
  - XLSX
  - HTML
  - Markdown
- Automatische PyInstaller build van een standalone EXE
- CyNiT look & feel met appelblauwzeegroen thema

## Gebruik

1. Start de tool:
   - `python cert_tool.py` voor GUI + Web
   - `python cert_tool.py --gui-only` alleen GUI
   - `python cert_tool.py --web` alleen Web

2. Kies een certificaat of CSR in de GUI of upload via de Web UI.

3. Bekijk de details of exporteer ze in het gewenste formaat.

## Over

CyNiT tools zijn ontworpen om het beheer van certificaten en
security workflows eenvoudiger te maken.
