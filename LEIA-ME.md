# Prumo PDF para Windows

Aplicativo para Windows que roda inteiramente no seu computador, sem enviar arquivos para a internet, sem coletar dados e sem custo por uso. A partir da versão 1.1.0, a aparência e a organização são as mesmas do Prumo PDF para iPhone.

- **Biblioteca** com cartões, como no iPhone: Todos os PDFs, Recentes, Aguardando OCR, Com OCR, Favoritos, Pastas e busca pelo nome e pelo texto dos PDFs.
- **OCR em português:** só as páginas em imagem passam pelo OCR; páginas que já têm texto ficam como estão. O resultado é uma cópia com “- OCR” no nome, na mesma pasta. Páginas com baixa confiança são marcadas para revisão.
- **Remover, extrair, dividir em partes iguais e combinar.** Na divisão, um PDF de 200 páginas em 4 partes vira “Nome - Parte 1” a “Parte 4”.
- **Desfazer** a última alteração de páginas de cada PDF.
- **Compartilhar:** copiar o arquivo para colar (Ctrl+V) no WhatsApp ou no e-mail, exportar uma cópia ou mostrar no Explorador.

Os PDFs ficam como arquivos comuns na pasta **Documentos › Prumo PDF** (dá para mudar em Ajustes). Para ter backup na nuvem que você usa, escolha uma pasta sincronizada pelo OneDrive, Google Drive, iCloud Drive ou Dropbox.

Ainda chegando nas próximas etapas: organizar páginas arrastando, incluir páginas, escanear pela webcam, leitor próprio com modo leitor, correção de páginas curvadas e trava com senha. A tela antiga (OCR em lote) continua disponível pelo atalho com `--classico`.

---

## 1. Gerar o instalador (uma vez só)

1. Descompacte esta pasta em um lugar fixo, por exemplo `C:\PrumoPDF`.
2. Dê dois cliques em **GERAR_INSTALADOR.bat**.
3. Aguarde. Na primeira vez leva cerca de 10 a 20 minutos, porque o script baixa o Python, as bibliotecas, os modelos de idioma e o Tesseract. É preciso estar conectado à internet nessa etapa.
4. Ao final, a pasta `dist` abre com o arquivo **Instalador_PrumoPDF_1.1.0.exe** selecionado.

Você **não** precisa instalar o Python antes: o script usa o `uv`, que baixa um Python próprio só para esta pasta, sem mexer no resto do computador.

Se o Windows pedir permissão para instalar o Inno Setup (programa que monta o instalador), aceite.

## 2. Instalar

1. Dê dois cliques em **Instalador_PrumoPDF_1.1.0.exe**.
2. Como o instalador não tem assinatura digital de empresa, o Windows pode mostrar “O Windows protegeu o computador”. Clique em **Mais informações** e depois em **Executar assim mesmo**.
3. O instalador coloca o Prumo PDF em Arquivos de Programas, cria os atalhos e, se o computador ainda não tiver, instala o **Tesseract** (o motor de OCR) automaticamente.

Depois disso, o programa funciona sem internet.

## 3. Usar

- **Importar:** cartão **Importar**, Ctrl+O, ou arraste PDFs (ou uma pasta) para a janela. Dentro de uma pasta, os PDFs arrastados entram nela.
- **Abrir um PDF:** clique no cartão. O botão direito mostra o menu rápido (ler, compartilhar, OCR, favoritar, renomear, mover, excluir).
- **Voltar:** botão redondo com a seta, Alt+←, Backspace ou o botão "voltar" do mouse.
- **Excluir** manda o arquivo para a Lixeira do Windows.
- **OCR:** na tela do PDF, cartão **OCR**. O andamento aparece no pé da janela; dá para continuar usando o programa.
- **Confiança:** para cada página que passou pelo OCR, o programa mostra a confiança média do Tesseract. Páginas abaixo de 85%, ou com mais de 10% das palavras com baixa confiança, são marcadas como **“Revisar”**. Esse número é a avaliação do próprio motor e não garante acerto: em documentos importantes, confira nomes, datas, números e valores no original.
- **Precisão máxima:** usa o modelo de idioma mais preciso do Tesseract e amplia imagens de baixa resolução. É bem mais lenta; use em documentos difíceis.
- **PDF com assinatura digital:** o OCR invalida a assinatura da cópia. Por isso o programa só faz OCR nesses arquivos se você marcar a opção correspondente. O original continua válido.

### Dicas para um OCR melhor
- Escaneie a 300 DPI, em tons de cinza, com a folha reta.
- Fotos de celular: boa iluminação, sem sombra, enquadrando só a folha.
- Texto manuscrito, carimbos sobrepostos e tabelas complexas tendem a ter mais erros.

## 4. Para quem for mexer no código

```
app/            código do aplicativo (Python + PySide6)
  main.py         ponto de entrada (janela, --classico, --ocr-worker, --self-test, --demo)
  app_window.py   janela principal, navegação, avisos e fila de OCR
  screens.py      telas no estilo do iPhone
  ios_theme.py    cores, fontes e ícones; ios_kit.py: cartões, busca, alertas
  library.py      biblioteca (pastas reais + metadados em .prumo/library.json)
  pdfops.py       remover, extrair, incluir, reorganizar, dividir
  services.py     miniaturas, análise em segundo plano, fila de OCR
  core.py         análise de páginas, combinar, extrair
  ocr_worker.py   processo separado que roda o OCR de um arquivo
  ocr_plugin.py   plugin do OCRmyPDF: confiança por página e progresso
  page_*.py       telas antigas (abertas com --classico)
tests/          testes automáticos: python -m unittest discover -s tests
build/          requirements, PyInstaller, Inno Setup e o script de build
tessdata_common/ arquivos de configuração do Tesseract usados pelo app
```

Rodar sem instalar (com o ambiente `.venv` já criado pelo build): `.venv\Scripts\python app\main.py`

Os critérios de classificação de página (quantidade mínima de texto, cobertura por imagem) ficam no início de `app/core.py`.

## 5. Componentes e licenças (todos gratuitos)

| Componente | Uso | Licença |
|---|---|---|
| Tesseract (UB Mannheim) | motor de OCR | Apache 2.0 |
| OCRmyPDF | monta o PDF com a camada de texto | MPL 2.0 |
| pypdfium2 / PDFium | leitura e miniaturas | Apache 2.0 / BSD |
| pikepdf, pypdf | combinar e extrair | MPL 2.0, BSD |
| PySide6 (Qt) | interface | LGPL v3 |

O Ghostscript **não** é usado: desde a versão 17, o OCRmyPDF consegue trabalhar sem ele.
