# EPG generated from your M3U

Arquivos gerados:
- epg.xml (XMLTV) — gerado automaticamente com 48 horas de grade.
- epg_generator.py — script Python para regenerar o epg.xml a partir da M3U (local ou URL).
- .github_generate_epg.yml — modelo de workflow do GitHub Actions (cole em .github/workflows/generate-epg.yml).

Instruções rápidas:

1) Para rodar localmente:
   - Instale dependências: pip install requests
   - Rode: python epg_generator.py "/caminho/para/sua_playlist.m3u"
   - O arquivo `epg.xml` será criado no diretório atual.

2) Para automatizar com GitHub Actions:
   - Crie um repositório público no GitHub.
   - Adicione os arquivos (epg_generator.py e .github/workflows/generate-epg.yml).
   - Substitua a URL M3U no workflow pela sua URL real se necessário.
   - Commit & push. O workflow irá rodar no schedule e commitar epg.xml atualizado.

3) URL pública:
   - Após push, o `epg.xml` estará no repositório. Para usar no MaxPlayer, você pode usar:
     https://raw.githubusercontent.com/<usuario>/<repo>/main/epg.xml
   - Ou ative o GitHub Pages e coloque `epg.xml` em docs/ para servir via:
     https://<usuario>.github.io/<repo>/epg.xml

Observação:
- Os horários foram gerados no fuso America/Recife (UTC-3) e possuem offset -0300.
- Se quiser uma grade real (não exemplos), me envie um CSV com colunas: tvg-id,start,stop,title,desc.
