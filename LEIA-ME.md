# Prumo PDF para Windows

Aplicativo para Windows que roda inteiramente no seu computador, sem enviar arquivos para a internet, sem coletar dados e sem custo por uso. A partir da versão 1.1.0, a aparência e a organização são as mesmas do Prumo PDF para iPhone.

- **Tela inicial com tudo:** as listas (Todos os PDFs, Recentes, Aguardando OCR, Com OCR, Favoritos, Pastas) e todas as ferramentas (Ler, Fazer OCR, Organizar, Incluir, Remover e Extrair páginas, Dividir, Combinar). Cada ferramenta pergunta qual PDF usar: um arquivo do computador ou um que já está no Prumo, filtrando por aba ou pasta.
- **Cartões de PDF** com a estrela de favorito (clique para preencher e mandar para Favoritos) e os três pontos ⋮ no canto inferior direito, que abrem as opções (o botão direito do mouse continua funcionando).
- **Pastas:** ao criar uma, já dá para adicionar PDFs do computador ou de qualquer parte do Prumo (outra pasta, Todos os PDFs, Favoritos…), movendo ou copiando.
- **Leitor próprio**, com zoom e troca entre o original e a cópia com OCR, sem precisar abrir outro programa:
  - **à esquerda, as miniaturas das páginas** (como no Word): rolam com o mouse e um clique leva à página;
  - **seleção de texto com o mouse** (dois cliques selecionam a palavra; Ctrl+C copia). Ao soltar o mouse, aparece uma **barrinha como a do Word**: **Destacar** (passando o mouse, abrem todas as cores; a lista fica aberta enquanto o mouse estiver no botão ou nas cores e some ao escolher uma), **Copiar**, **Tirar destaque** (só aparece se parte do trecho já estiver destacada) e **Adicionar ao resumo**;
  - **botão direito arrastado sobre o texto** destaca com a última cor usada (amarelo, se ainda não escolheu nenhuma). Um clique simples com o botão direito, sem arrastar, continua abrindo o menu;
  - **desfazer e refazer:** as setas ← e → no alto, logo depois da divisória das miniaturas (ou Ctrl+Z e Ctrl+Y / Ctrl+Shift+Z), desfazem e refazem destaques, troca de cor, trechos levados ao resumo e, quando feitos pelo leitor, corte, giro, numeração e inclusão de páginas;
  - **à direita, o painel**: cores de destaque (amarelo, verde, azul, rosa e laranja), borracha e botões para todas as funções do app. Escolha a cor e arraste sobre o texto. O destaque fica gravado no próprio PDF, como anotação padrão, e aparece no Adobe, no Edge, no Chrome e no iPhone. O botão direito sobre um destaque apaga ou muda a cor;
  - **Adicionar ao resumo deste PDF**: o trecho selecionado vai para “Nome - resumo.pdf”, na mesma pasta, com “Trecho extraído da página 10” (ou “das páginas 10-11”) embaixo, em letra menor. Cada trecho novo entra no fim do mesmo resumo.
- **Cortar e girar páginas:** a página aparece inteira com uma moldura que se arrasta pelas bordas (ou margens em milímetros, ou “Margens automáticas”); girar 90° ou 180°; vale para esta página, todas, pares, ímpares ou um trecho. O corte usa o recorte padrão do PDF: nada é apagado, e “Página inteira” desfaz.
- **Numerar páginas:** seis posições, formatos “1”, “Página 1”, “Página 1 de 12”, “1/12” e “- 1 -”, número inicial, a partir de qual página e tamanho da letra. O número vira texto de verdade na página.
- **Seleção com o mouse:** clicar e arrastar desenha um retângulo que seleciona vários PDFs (nas listas, nas pastas e ao escolher PDFs) ou várias páginas (Remover, Extrair e Organizar). Ctrl soma à seleção.
- **Modo leitor (Texto):** só o texto (do OCR ou do próprio PDF), em parágrafos, numa coluna confortável; letra maior ou menor (A−/A+), fonte com ou sem serifa e fundo branco, sépia ou escuro. Tem as mesmas funções do modo Página: miniaturas, barrinha de seleção, cores e borracha, botão direito arrastado, desfazer e refazer, resumo, busca e o painel com todas as ferramentas. Os destaques feitos no texto vão para o PDF e aparecem também no modo Página (e vice-versa). Páginas com baixa confiança no OCR aparecem marcadas.
- **Busca dentro do PDF (Ctrl+F)**, nas páginas e no modo leitor: não precisa de acentos nem maiúsculas (“indenizacao” acha “Indenização”), destaca todas as ocorrências e anda entre elas com Enter / Shift+Enter ou F3.
- **Organizar páginas:** arraste para mudar a ordem (a lista rola sozinha perto das bordas), gire, exclua, desfaça; Ctrl+roda do mouse muda o tamanho das miniaturas. Para ler uma página, clique na lupa que aparece sobre ela (ou dois cliques, ou Espaço): ela abre grande ali mesmo, já com o giro, e as setas passam para as outras.
- **Incluir páginas** de outro PDF (ou do próprio): todas ou trechos como 5-15, no início, no fim ou depois de uma página.
- **Corrigir páginas curvas:** fotos de livros e revistas (página curvada perto da lombada), papel ondulado ou dobrado ficam com o texto reto, o que também melhora o OCR. Na tela do PDF, “Corrigir páginas curvas” mostra o antes e o depois e cria uma cópia “- corrigido” (só as páginas escolhidas mudam). Em Ajustes, dá para corrigir automaticamente as fotos ao converter. Usa o modelo UVDoc, que roda inteiramente no computador.
- **Segurança:** em Ajustes, uma **senha para abrir o Prumo** (bloqueia ao abrir, depois de um tempo sem uso e com Ctrl+L). Na tela do PDF, **Proteger com senha** cria uma cópia com a criptografia padrão de PDF (AES-256), que abre em qualquer leitor com a senha (letras, números e símbolos; a tela mostra a força da senha e tem “Mostrar a senha”); **Remover senha** cria uma cópia sem senha (sabendo a senha), para fazer OCR, organizar ou dividir. PDFs com senha aparecem com um cadeado e pedem a senha ao abrir no leitor.
- **Converter em PDF:** fotos e imagens (JPG, PNG, HEIC do iPhone, TIFF de várias páginas, BMP, GIF, WebP), Word, Excel e PowerPoint (DOC, DOCX, RTF, ODT, XLS, XLSX, ODS, PPT, PPTX, ODP), texto (TXT, CSV) e HTML. Várias fotos podem virar um PDF só, uma por página A4, ou um PDF para cada; depois, o app pergunta se quer fazer o OCR. Os arquivos do Office são convertidos pelo próprio Office instalado (como o “Salvar como PDF”) ou, sem Office, pelo LibreOffice; sem nenhum dos dois, um .docx ainda é convertido de forma simplificada. Também dá para importar ou arrastar esses arquivos direto: eles viram PDF na hora.
- **OCR em português:** só as páginas em imagem passam pelo OCR; páginas que já têm texto ficam como estão. O resultado é uma cópia com “- OCR” no nome, na mesma pasta. Páginas com baixa confiança são marcadas para revisão.
- **Remover, extrair, dividir em partes iguais e combinar.** Na divisão, um PDF de 200 páginas em 4 partes vira “Nome - Parte 1” a “Parte 4”.
- **Desfazer** a última alteração de páginas de cada PDF.
- **Assinatura digital (PAdES):** na tela do PDF, **Assinar digitalmente**, com certificado **A1** (arquivo .pfx ou .p12, guardado no Prumo; a senha é pedida a cada assinatura e não fica gravada) ou **A3** (token ou cartão: com o programa do fabricante instalado, o certificado aparece no Windows e o próprio programa pede o PIN). A assinatura pode aparecer como carimbo na página (primeira ou última, em um dos cantos) ou ficar invisível. **Depois de assinado, o PDF não pode mais ser alterado**: qualquer mudança (destaque, corte, numeração, páginas) invalida a assinatura. Por isso o Prumo assina uma cópia, “Nome - assinado”, e deixa o original como está; na cópia, as ferramentas de edição ficam desligadas e o cartão mostra “Assinado”. Uma segunda pessoa pode assinar a mesma cópia: a nova assinatura entra no próprio arquivo e as anteriores continuam válidas. A primeira assinatura é de certificação (permite só novas assinaturas), o que o Adobe Reader e o Verificador de Conformidade do ITI (validar.iti.gov.br) conseguem conferir. Os certificados ficam em Ajustes › Assinatura digital.
- **Compartilhar:** copiar o arquivo para colar (Ctrl+V) no WhatsApp ou no e-mail, exportar uma cópia ou mostrar no Explorador.

Os PDFs ficam como arquivos comuns na pasta **Documentos › Prumo PDF** (dá para mudar em Ajustes).

- **Backup:** os Ajustes mostram se os PDFs estão só neste computador ou numa nuvem. Se o OneDrive, o Google Drive, o iCloud Drive ou o Dropbox estiverem instalados, um clique leva a biblioteca para lá (com backup automático). Também dá para fazer uma **cópia de segurança** completa (PDFs, pastas e favoritos) num pendrive ou HD externo e **restaurar** depois, sem duplicar arquivos. A cópia é uma pasta comum e abre também no Prumo para iPhone.
- **No Windows:** o Prumo aparece em **Abrir com** nos PDFs (sem trocar o seu leitor padrão) e, no botão direito de fotos e arquivos do Word, Excel e PowerPoint, em **Converter em PDF com o Prumo**. Com o Prumo já aberto, os arquivos vão para a mesma janela.

A tela antiga (OCR em lote) continua disponível pelo atalho com `--classico`.

---

## 1. Instalar

1. Baixe o **PrumoPDF_Setup_1.10.0.exe**: ele vem pronto, já com o Tesseract, e também fica na página **Releases** deste repositório (“Prumo PDF para Windows (última versão)”).
2. Dê dois cliques nele. Como o instalador não tem assinatura digital de empresa, o Windows pode mostrar “O Windows protegeu o computador”. Clique em **Mais informações** e depois em **Executar assim mesmo**.
3. O instalador coloca o Prumo PDF em Arquivos de Programas, cria os atalhos e, se o computador ainda não tiver, instala o **Tesseract** (o motor de OCR) automaticamente.

Para atualizar, rode o instalador da versão nova por cima: os PDFs e os ajustes continuam onde estão.

O instalador é gerado automaticamente no GitHub a cada mudança (Windows de verdade, com os testes automáticos rodando antes). Se um dia precisar gerar no próprio computador, o **GERAR_INSTALADOR.bat** continua funcionando.

Depois disso, o programa funciona sem internet.

## 2. Usar

- **Importar:** cartão **Importar**, Ctrl+O, ou arraste PDFs (ou uma pasta) para a janela. Dentro de uma pasta, os PDFs arrastados entram nela.
- **Abrir um PDF:** clique no cartão. Os três pontos ⋮ no canto inferior direito (ou o botão direito do mouse) mostram o menu rápido; a estrela favorita.
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

### Backup e sincronização com o iPhone

Em **Ajustes › Escolher nuvem**, escolha onde guardar os PDFs. O Prumo usa uma pasta "Prumo PDF" dentro da nuvem; o mesmo vale no iPhone (Ajustes › Escolher nuvem).

- **iCloud Drive** (recomendado para quem usa iPhone): instale o iCloud para Windows (Microsoft Store), entre com a conta Apple e ligue o iCloud Drive. No iPhone, escolha o iCloud Drive no Prumo.
- **Google Drive, OneDrive, Dropbox**: funcionam como backup e para sincronizar entre computadores. No iPhone, o Google Drive e o OneDrive não deixam outros apps usarem pastas deles; o Dropbox depende do app dele.
- Favoritos e a ligação com as cópias de OCR vão junto (arquivo oculto `.prumo\library.json`). Se os dois aparelhos mudarem ao mesmo tempo, o Prumo junta as mudanças.

### Esqueci a senha do Prumo

Por segurança, não há como ver a senha. Para desfazer o bloqueio, feche o Prumo, abra o **Prompt de Comando** (menu Iniciar › digite “cmd”) e rode:

```
reg delete "HKCU\Software\Prumo\PrumoPDF" /v app_lock_hash /f
```

Na próxima vez, o Prumo abre sem senha (e dá para criar outra em Ajustes). Os PDFs não são afetados: continuam na pasta da biblioteca. Isso vale só para a senha do app: **a senha de um PDF protegido não tem como ser recuperada**, nem pelo Prumo nem por outro programa.

## 3. Para quem for mexer no código

```
app/            código do aplicativo (Python + PySide6)
  main.py         ponto de entrada (janela, --classico, --ocr-worker, --self-test, --demo)
  app_window.py   janela principal, navegação, avisos e fila de OCR
  screens.py      telas no estilo do iPhone
  ios_theme.py    cores, fontes e ícones; ios_kit.py: cartões, busca, alertas
  reader.py       leitor (modos Página e Texto): miniaturas, seleção, destaques e painel de ferramentas
  reader_select.py barrinha que aparece ao selecionar texto (cores, copiar, tirar destaque, resumo)
  reader_history.py desfazer e refazer no leitor (cópias do arquivo antes e depois de cada mudança)
  reader_text.py  texto das páginas (busca, modo leitor, posições para selecionar)
  signing.py      assinatura digital PAdES (A1 em .pfx e A3/A1 do Windows, com o pyHanko)
  sign_ui.py      telas de assinar e a seção “Assinatura digital” dos Ajustes
  annotations.py  destaques gravados no PDF (anotações /Highlight)
  summary.py      “Adicionar ao resumo” (Nome - resumo.pdf; trechos em .prumo/resumos)
  page_tools.py   cortar, girar e numerar páginas (as contas ficam em pdfops.py)
  page_view.py    página grande por cima da tela (Organizar, Remover, Extrair)
  rubberband.py   retângulo de seleção com o mouse
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

## 4. Componentes e licenças (todos gratuitos)

| Componente | Uso | Licença |
|---|---|---|
| Tesseract (UB Mannheim) | motor de OCR | Apache 2.0 |
| OCRmyPDF | monta o PDF com a camada de texto | MPL 2.0 |
| pypdfium2 / PDFium | leitura e miniaturas | Apache 2.0 / BSD |
| pikepdf, pypdf | combinar e extrair | MPL 2.0, BSD |
| PySide6 (Qt) | interface | LGPL v3 |
| img2pdf, Pillow | imagens em PDF sem perda de qualidade | LGPL v3, MIT-CMU |
| pillow-heif (libheif) | fotos HEIC do iPhone | BSD-3 (libheif: LGPL v3) |
| mammoth | .docx em PDF sem o Word | BSD-2 |
| fpdf2 | texto, HTML e .docx em PDF com texto selecionável | LGPL v3 |
| UVDoc (Verhoeven, Magne, Sorkine-Hornung, SIGGRAPH Asia 2023) | modelo de correção de páginas curvas (models/uvdoc.onnx, exportado do original) | MIT |
| ONNX Runtime, NumPy | roda o modelo UVDoc no computador | MIT, BSD-3 |
| pyHanko | assinatura digital PAdES | MIT |

O Ghostscript **não** é usado: desde a versão 17, o OCRmyPDF consegue trabalhar sem ele.
