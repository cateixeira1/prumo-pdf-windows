"""
Gera app/locales/*.json a partir das tabelas abaixo. Rodar:  python tools/build_locales.py

CORE: textos mais vistos, em todos os idiomas (colunas na ordem de COLS).
MORE: o restante da interface, só em inglês (idiomas sem tradução própria caem no inglês).
"""
import json
from pathlib import Path

COLS = ["en", "es", "fr", "de", "ja", "zh-CN", "zh-TW", "nb", "sv", "da", "fi"]

CORE = """
Todos os PDFs|All PDFs|Todos los PDF|Tous les PDF|Alle PDFs|すべてのPDF|所有 PDF|所有 PDF|Alle PDF-er|Alla PDF:er|Alle PDF'er|Kaikki PDF:t
Recentes|Recent|Recientes|Récents|Zuletzt|最近|最近|最近|Nylige|Senaste|Seneste|Viimeisimmät
Favoritos|Favorites|Favoritos|Favoris|Favoriten|お気に入り|收藏|我的最愛|Favoritter|Favoriter|Favoritter|Suosikit
Com OCR|With OCR|Con OCR|Avec OCR|Mit OCR|OCRあり|已 OCR|已 OCR|Med OCR|Med OCR|Med OCR|OCR tehty
Sem OCR|No OCR|Sin OCR|Sans OCR|Ohne OCR|OCRなし|无 OCR|無 OCR|Uten OCR|Utan OCR|Uden OCR|Ei OCR:ää
Pastas|Folders|Carpetas|Dossiers|Ordner|フォルダ|文件夹|資料夾|Mapper|Mappar|Mapper|Kansiot
Ferramentas|Tools|Herramientas|Outils|Werkzeuge|ツール|工具|工具|Verktøy|Verktyg|Værktøjer|Työkalut
Ajustes|Settings|Ajustes|Réglages|Einstellungen|設定|设置|設定|Innstillinger|Inställningar|Indstillinger|Asetukset
Buscar|Search|Buscar|Rechercher|Suchen|検索|搜索|搜尋|Søk|Sök|Søg|Hae
Importar|Import|Importar|Importer|Importieren|読み込む|导入|匯入|Importer|Importera|Importer|Tuo
Selecionar|Select|Seleccionar|Sélectionner|Auswählen|選択|选择|選取|Velg|Välj|Vælg|Valitse
Ordenar|Sort|Ordenar|Trier|Sortieren|並べ替え|排序|排序|Sorter|Sortera|Sortér|Lajittele
Cancelar|Cancel|Cancelar|Annuler|Abbrechen|キャンセル|取消|取消|Avbryt|Avbryt|Annuller|Peruuta
Fechar|Close|Cerrar|Fermer|Schließen|閉じる|关闭|關閉|Lukk|Stäng|Luk|Sulje
Salvar|Save|Guardar|Enregistrer|Speichern|保存|保存|儲存|Lagre|Spara|Gem|Tallenna
Abrir|Open|Abrir|Ouvrir|Öffnen|開く|打开|開啟|Åpne|Öppna|Åbn|Avaa
Aplicar|Apply|Aplicar|Appliquer|Anwenden|適用|应用|套用|Bruk|Tillämpa|Anvend|Käytä
Continuar|Continue|Continuar|Continuer|Weiter|続ける|继续|繼續|Fortsett|Fortsätt|Fortsæt|Jatka
Voltar|Back|Volver|Retour|Zurück|戻る|返回|返回|Tilbake|Tillbaka|Tilbage|Takaisin
Sim|Yes|Sí|Oui|Ja|はい|是|是|Ja|Ja|Ja|Kyllä
Excluir|Delete|Eliminar|Supprimer|Löschen|削除|删除|刪除|Slett|Ta bort|Slet|Poista
Renomear|Rename|Cambiar nombre|Renommer|Umbenennen|名前を変更|重命名|重新命名|Gi nytt navn|Byt namn|Omdøb|Nimeä uudelleen
Duplicar|Duplicate|Duplicar|Dupliquer|Duplizieren|複製|复制副本|製作副本|Dupliser|Duplicera|Duplikér|Monista
Mover|Move|Mover|Déplacer|Verschieben|移動|移动|移動|Flytt|Flytta|Flyt|Siirrä
Copiar|Copy|Copiar|Copier|Kopieren|コピー|复制|拷貝|Kopier|Kopiera|Kopiér|Kopioi
Compartilhar…|Share…|Compartir…|Partager…|Teilen …|共有…|共享…|分享…|Del …|Dela …|Del …|Jaa…
Desfazer|Undo|Deshacer|Annuler|Rückgängig|元に戻す|撤销|還原|Angre|Ångra|Fortryd|Kumoa
Remover|Remove|Quitar|Retirer|Entfernen|削除|移除|移除|Fjern|Ta bort|Fjern|Poista
Adicionar|Add|Añadir|Ajouter|Hinzufügen|追加|添加|加入|Legg til|Lägg till|Tilføj|Lisää
Criar|Create|Crear|Créer|Erstellen|作成|创建|建立|Opprett|Skapa|Opret|Luo
Mostrar|Show|Mostrar|Afficher|Anzeigen|表示|显示|顯示|Vis|Visa|Vis|Näytä
Senha|Password|Contraseña|Mot de passe|Passwort|パスワード|密码|密碼|Passord|Lösenord|Adgangskode|Salasana
Escuro|Dark|Oscuro|Sombre|Dunkel|ダーク|深色|深色|Mørk|Mörkt|Mørk|Tumma
Claro|Light|Claro|Clair|Hell|ライト|浅色|淺色|Lys|Ljust|Lys|Vaalea
Aparência|Appearance|Apariencia|Apparence|Erscheinungsbild|外観|外观|外觀|Utseende|Utseende|Udseende|Ulkoasu
Igual ao Windows|Same as Windows|Igual que Windows|Comme Windows|Wie Windows|Windowsに合わせる|跟随 Windows|跟隨 Windows|Som Windows|Som Windows|Som Windows|Kuten Windowsissa
Sobre|About|Acerca de|À propos|Info|情報|关于|關於|Om|Om|Om|Tietoja
Segurança|Security|Seguridad|Sécurité|Sicherheit|セキュリティ|安全|安全性|Sikkerhet|Säkerhet|Sikkerhed|Turvallisuus
Nome|Name|Nombre|Nom|Name|名前|名称|名稱|Navn|Namn|Navn|Nimi
Posição|Position|Posición|Position|Position|位置|位置|位置|Posisjon|Position|Placering|Sijainti
Formato|Format|Formato|Format|Format|形式|格式|格式|Format|Format|Format|Muoto
Páginas|Pages|Páginas|Pages|Seiten|ページ|页面|頁面|Sider|Sidor|Sider|Sivut
Todas|All|Todas|Toutes|Alle|すべて|全部|全部|Alle|Alla|Alle|Kaikki
Nenhuma|None|Ninguna|Aucune|Keine|なし|无|無|Ingen|Ingen|Ingen|Ei yhtään
Inverter|Invert|Invertir|Inverser|Umkehren|反転|反选|反向選取|Inverter|Invertera|Inverter|Käännä
Assinar|Sign|Firmar|Signer|Signieren|署名|签名|簽署|Signer|Signera|Underskriv|Allekirjoita
Assinar digitalmente|Sign digitally|Firmar digitalmente|Signer numériquement|Digital signieren|電子署名する|数字签名|數位簽署|Signer digitalt|Signera digitalt|Underskriv digitalt|Allekirjoita sähköisesti
Assinado|Signed|Firmado|Signé|Signiert|署名済み|已签名|已簽署|Signert|Signerad|Underskrevet|Allekirjoitettu
Assinado digitalmente|Digitally signed|Firmado digitalmente|Signé numériquement|Digital signiert|電子署名済み|已数字签名|已數位簽署|Digitalt signert|Digitalt signerad|Digitalt underskrevet|Sähköisesti allekirjoitettu
Numerar páginas|Number pages|Numerar páginas|Numéroter les pages|Seiten nummerieren|ページ番号を付ける|添加页码|加入頁碼|Nummerer sider|Numrera sidor|Nummerér sider|Numeroi sivut
Numerar|Number|Numerar|Numéroter|Nummerieren|番号を付ける|编号|編號|Nummerer|Numrera|Nummerér|Numeroi
Organizar páginas|Organize pages|Organizar páginas|Organiser les pages|Seiten organisieren|ページを整理|整理页面|整理頁面|Organiser sider|Organisera sidor|Organisér sider|Järjestä sivut
Combinar PDFs|Combine PDFs|Combinar PDF|Fusionner des PDF|PDFs zusammenfügen|PDFを結合|合并 PDF|合併 PDF|Slå sammen PDF-er|Kombinera PDF:er|Kombinér PDF'er|Yhdistä PDF:t
Extrair páginas|Extract pages|Extraer páginas|Extraire des pages|Seiten extrahieren|ページを抽出|提取页面|擷取頁面|Trekk ut sider|Extrahera sidor|Udtræk sider|Poimi sivut
Dividir em partes|Split into parts|Dividir en partes|Diviser en parties|In Teile aufteilen|分割する|拆分为多个部分|分割成多個部分|Del i deler|Dela upp i delar|Opdel i dele|Jaa osiin
Proteger com senha|Protect with password|Proteger con contraseña|Protéger par mot de passe|Mit Passwort schützen|パスワードで保護|用密码保护|以密碼保護|Beskytt med passord|Skydda med lösenord|Beskyt med adgangskode|Suojaa salasanalla
Remover senha|Remove password|Quitar contraseña|Retirer le mot de passe|Passwort entfernen|パスワードを解除|移除密码|移除密碼|Fjern passord|Ta bort lösenord|Fjern adgangskode|Poista salasana
Cortar e girar páginas|Crop and rotate pages|Recortar y girar páginas|Rogner et pivoter les pages|Seiten zuschneiden und drehen|ページをトリミング・回転|裁剪并旋转页面|裁切並旋轉頁面|Beskjær og roter sider|Beskär och rotera sidor|Beskær og roter sider|Rajaa ja käännä sivuja
Cortar e girar|Crop and rotate|Recortar y girar|Rogner et pivoter|Zuschneiden und drehen|トリミング・回転|裁剪并旋转|裁切並旋轉|Beskjær og roter|Beskär och rotera|Beskær og roter|Rajaa ja käännä
Corrigir páginas curvas|Fix curved pages|Corregir páginas curvas|Corriger les pages courbées|Gewölbte Seiten korrigieren|湾曲したページを補正|矫正弯曲页面|校正彎曲頁面|Rett opp krumme sider|Korrigera böjda sidor|Ret buede sider|Korjaa kaareutuneet sivut
Incluir páginas|Insert pages|Insertar páginas|Insérer des pages|Seiten einfügen|ページを挿入|插入页面|插入頁面|Sett inn sider|Infoga sidor|Indsæt sider|Lisää sivuja
Remover páginas|Remove pages|Quitar páginas|Supprimer des pages|Seiten entfernen|ページを削除|删除页面|刪除頁面|Fjern sider|Ta bort sidor|Fjern sider|Poista sivuja
Fazer OCR|Run OCR|Hacer OCR|Lancer l’OCR|OCR ausführen|OCRを実行|执行 OCR|執行 OCR|Kjør OCR|Kör OCR|Kør OCR|Suorita OCR
Nenhum PDF|No PDFs|Ningún PDF|Aucun PDF|Keine PDFs|PDFがありません|没有 PDF|沒有 PDF|Ingen PDF-er|Inga PDF:er|Ingen PDF'er|Ei PDF:iä
Nenhum favorito|No favorites|Ningún favorito|Aucun favori|Keine Favoriten|お気に入りはありません|没有收藏|沒有收藏|Ingen favoritter|Inga favoriter|Ingen favoritter|Ei suosikkeja
Nada encontrado|Nothing found|No se encontró nada|Aucun résultat|Nichts gefunden|見つかりません|未找到|找不到|Fant ingenting|Inget hittades|Intet fundet|Ei tuloksia
Carregando…|Loading…|Cargando…|Chargement…|Wird geladen …|読み込み中…|正在加载…|載入中…|Laster …|Läser in …|Indlæser …|Ladataan…
Esquerda|Left|Izquierda|Gauche|Links|左|左|左|Venstre|Vänster|Venstre|Vasen
Direita|Right|Derecha|Droite|Rechts|右|右|右|Høyre|Höger|Højre|Oikea
Alto|Top|Arriba|Haut|Oben|上|上|上|Topp|Överkant|Top|Ylä
Baixo|Bottom|Abajo|Bas|Unten|下|下|下|Bunn|Nederkant|Bund|Ala
Girar|Rotate|Girar|Pivoter|Drehen|回転|旋转|旋轉|Roter|Rotera|Roter|Käännä
Margens (mm)|Margins (mm)|Márgenes (mm)|Marges (mm)|Ränder (mm)|余白 (mm)|边距 (毫米)|邊界 (公釐)|Marger (mm)|Marginaler (mm)|Margener (mm)|Marginaalit (mm)
Prévia|Preview|Vista previa|Aperçu|Vorschau|プレビュー|预览|預覽|Forhåndsvisning|Förhandsvisning|Forhåndsvisning|Esikatselu
Idioma do aplicativo|App language|Idioma de la aplicación|Langue de l’application|Sprache der App|アプリの言語|应用语言|App 語言|Appspråk|Appens språk|Appens sprog|Sovelluksen kieli
Automático (idioma do Windows)|Automatic (Windows language)|Automático (idioma de Windows)|Automatique (langue de Windows)|Automatisch (Windows-Sprache)|自動 (Windowsの言語)|自动 (Windows 语言)|自動 (Windows 語言)|Automatisk (Windows-språk)|Automatiskt (Windows-språk)|Automatisk (Windows-sprog)|Automaattinen (Windowsin kieli)
Em andamento…|In progress…|En curso…|En cours…|Wird ausgeführt …|処理中…|进行中…|進行中…|Pågår …|Pågår …|I gang …|Käynnissä…
Mais recentes|Newest|Más recientes|Plus récents|Neueste|新しい順|最新|最新|Nyeste|Senaste|Nyeste|Uusimmat
Mais opções|More options|Más opciones|Plus d’options|Weitere Optionen|その他のオプション|更多选项|更多選項|Flere valg|Fler alternativ|Flere muligheder|Lisää vaihtoehtoja
Nova pasta|New folder|Nueva carpeta|Nouveau dossier|Neuer Ordner|新規フォルダ|新建文件夹|新增資料夾|Ny mappe|Ny mapp|Ny mappe|Uusi kansio
Nome da pasta|Folder name|Nombre de la carpeta|Nom du dossier|Ordnername|フォルダ名|文件夹名称|資料夾名稱|Mappenavn|Mappnamn|Mappenavn|Kansion nimi
Nome do PDF|PDF name|Nombre del PDF|Nom du PDF|PDF-Name|PDF名|PDF 名称|PDF 名稱|PDF-navn|PDF-namn|PDF-navn|PDF:n nimi
Buscar nome ou texto|Search name or text|Buscar nombre o texto|Rechercher un nom ou du texte|Name oder Text suchen|名前またはテキストを検索|搜索名称或文字|搜尋名稱或文字|Søk etter navn eller tekst|Sök namn eller text|Søg efter navn eller tekst|Hae nimeä tai tekstiä
Mostrar no Explorador|Show in Explorer|Mostrar en el Explorador|Afficher dans l’Explorateur|Im Explorer anzeigen|エクスプローラーで表示|在资源管理器中显示|在檔案總管中顯示|Vis i Utforsker|Visa i Utforskaren|Vis i Stifinder|Näytä Resurssienhallinnassa
Desfazer última alteração|Undo last change|Deshacer el último cambio|Annuler la dernière modification|Letzte Änderung rückgängig|直前の変更を元に戻す|撤销上次更改|還原上次變更|Angre siste endring|Ångra senaste ändring|Fortryd seneste ændring|Kumoa viimeisin muutos
Certificado|Certificate|Certificado|Certificat|Zertifikat|証明書|证书|憑證|Sertifikat|Certifikat|Certifikat|Varmenne
Assinar|Sign|Firmar|Signer|Signieren|署名|签名|簽署|Signer|Signera|Underskriv|Allekirjoita
Voltar (Alt+←)|Back (Alt+←)|Volver (Alt+←)|Retour (Alt+←)|Zurück (Alt+←)|戻る (Alt+←)|返回 (Alt+←)|返回 (Alt+←)|Tilbake (Alt+←)|Tillbaka (Alt+←)|Tilbage (Alt+←)|Takaisin (Alt+←)
Opções|Options|Opciones|Options|Optionen|オプション|选项|選項|Alternativer|Alternativ|Indstillinger|Valinnat
Revisar|Review|Revisar|Vérifier|Prüfen|確認|检查|檢查|Gjennomgå|Granska|Gennemgå|Tarkista
Texto|Text|Texto|Texte|Text|テキスト|文本|文字|Tekst|Text|Tekst|Teksti
Escaneado|Scanned|Escaneado|Numérisé|Gescannt|スキャン|扫描件|掃描|Skannet|Skannad|Scannet|Skannattu
Sem pasta|No folder|Sin carpeta|Sans dossier|Ohne Ordner|フォルダなし|无文件夹|無資料夾|Ingen mappe|Ingen mapp|Ingen mappe|Ei kansiota
1 página|1 page|1 página|1 page|1 Seite|1ページ|1 页|1 頁|1 side|1 sida|1 side|1 sivu
{} páginas|{} pages|{} páginas|{} pages|{} Seiten|{}ページ|{} 页|{} 頁|{} sider|{} sidor|{} sider|{} sivua
Alterado em {}|Modified {}|Modificado el {}|Modifié le {}|Geändert am {}|{} に変更|修改于 {}|修改於 {}|Endret {}|Ändrad {}|Ændret {}|Muokattu {}
Página {} de {}|Page {} of {}|Página {} de {}|Page {} sur {}|Seite {} von {}|{} / {} ページ|第 {} 页，共 {} 页|第 {} 頁，共 {} 頁|Side {} av {}|Sida {} av {}|Side {} af {}|Sivu {} / {}
Buscar em {}|Search in {}|Buscar en {}|Rechercher dans {}|In {} suchen|{} 内を検索|在 {} 中搜索|在 {} 中搜尋|Søk i {}|Sök i {}|Søg i {}|Hae kohteesta {}
""".strip().splitlines()

MORE = """
O Prumo segue o idioma do iPhone. Para usar outro só no Prumo, abra os Ajustes do iPhone, toque em Prumo PDF e em Idioma.|Prumo follows the iPhone language. To use a different one only in Prumo, open iPhone Settings, tap Prumo PDF and then Language.
Abrir os Ajustes do iPhone|Open iPhone Settings
Idiomas: português, inglês, espanhol, francês, alemão, japonês, chinês (simplificado e tradicional), norueguês, sueco, dinamarquês e finlandês. O que não estiver traduzido aparece em inglês. As traduções pedem revisão por quem fala a língua.|Languages: Portuguese, English, Spanish, French, German, Japanese, Chinese (Simplified and Traditional), Norwegian, Swedish, Danish and Finnish. Anything not translated appears in English. The translations need review by a speaker of the language.
Este iPhone não reconhece: {}. A Apple não oferece esses idiomas no OCR do iOS. Para eles, faça o OCR no Prumo para Windows: o PDF com OCR volta para cá pela mesma nuvem.|This iPhone doesn’t recognize: {}. Apple doesn’t offer these languages in iOS OCR. For them, run OCR in Prumo for Windows: the OCR’d PDF comes back here through the same cloud.
Prumo PDF está bloqueado|Prumo PDF is locked
Senha do Prumo|Prumo password
Desbloquear|Unlock
Esqueci a senha|I forgot my password
Senha incorreta.|Wrong password.
Escolher PDFs no computador|Choose PDFs on this computer
Converter em PDF|Convert to PDF
Importar PDFs (ou arquivos para converter)|Import PDFs (or files to convert)
Importando…|Importing…
Convertendo em PDF…|Converting to PDF…
Exportar cópia|Export copy
Exportar cópia para…|Export copy to…
Cópia exportada.|Copy exported.
Cancelar o OCR?|Cancel OCR?
Cancelar OCR|Cancel OCR
O arquivo original não muda.|The original file does not change.
OCR em andamento|OCR in progress
Fechar o Prumo PDF cancela o OCR. O arquivo original não muda.|Closing Prumo PDF cancels the OCR. The original file does not change.
Usar OCR agora?|Run OCR now?
Mais tarde|Later
Modo leitor (só o texto)|Reader mode (text only)
Como você quer ler?|How do you want to read?
O modo leitor mostra o texto reconhecido pelo OCR em parágrafos, como uma nota. Dá para alternar entre os modos a qualquer momento, no alto do leitor.|Reader mode shows the text recognized by OCR in paragraphs, like a note. You can switch modes at any time, at the top of the reader.
Com OCR (página com texto)|With OCR (page with text)
Um PDF só|One single PDF
Um PDF para cada|One PDF for each
Escolher a pasta da biblioteca|Choose the library folder
Mudar a pasta da biblioteca|Change the library folder
Pasta da biblioteca alterada.|Library folder changed.
Movendo os PDFs…|Moving the PDFs…
Mover os PDFs|Move the PDFs
Não mover|Don’t move
Juntar|Merge
Não juntar|Don’t merge
Juntando os PDFs…|Merging the PDFs…
Fazendo a cópia de segurança…|Making the backup…
Cópia de segurança|Backup
Fazer uma cópia agora…|Make a copy now…
Restaurar de uma cópia|Restore from a backup
Restaurar de uma cópia…|Restore from a backup…
Restaurando…|Restoring…
Nenhuma cópia feita ainda.|No backup made yet.
Backup e sincronização|Backup and sync
Trocar de nuvem…|Change cloud…
Escolher nuvem…|Choose cloud…
Só neste computador|Only on this computer
Em uso|In use
Entrar ou instalar…|Sign in or install…
Procurar de novo|Search again
Abrir no Explorador|Open in Explorer
Usar outra pasta…|Use another folder…
Windows|Windows
Aplicativos padrão do Windows…|Windows default apps…
Idiomas dos documentos|Document languages
Precisão máxima (bem mais lento)|Maximum accuracy (much slower)
Fotos|Photos
Desenvolvido por Color Software|Developed by Color Software
Senha para abrir o Prumo: ligada|Password to open Prumo: on
Senha para abrir o Prumo: desligada|Password to open Prumo: off
Mudar senha…|Change password…
Remover senha…|Remove password…
Criar senha…|Create password…
Só ao abrir o Prumo|Only when opening Prumo
Depois de 1 minuto sem uso|After 1 minute idle
Depois de 5 minutos sem uso|After 5 minutes idle
Depois de 10 minutos sem uso|After 10 minutes idle
Depois de 30 minutos sem uso|After 30 minutes idle
Senha salva. O Prumo vai pedir a senha ao abrir (e Ctrl+L bloqueia na hora).|Password saved. Prumo will ask for it on opening (and Ctrl+L locks it right away).
Senha atual|Current password
Nova senha do Prumo|New Prumo password
Criar senha do Prumo|Create Prumo password
Mudar a senha do Prumo|Change the Prumo password
Remover a senha do Prumo|Remove the Prumo password
Repita a senha|Repeat the password
Senha forte.|Strong password.
Senha fraca: use 8 ou mais caracteres, com letras e números.|Weak password: use 8 or more characters, with letters and numbers.
Senha média. Fica mais forte com mais caracteres, números e símbolos.|Fair password. It gets stronger with more characters, numbers and symbols.
As senhas não são iguais.|The passwords don’t match.
Senha atual incorreta.|Current password is wrong.
Use pelo menos 4 caracteres.|Use at least 4 characters.
Mostrar a senha|Show password
Proteger|Protect
Remover a senha|Remove the password
Senha (letras, números e símbolos)|Password (letters, numbers and symbols)
Salvar senha|Save password
Nenhum PDF sem OCR|No PDFs without OCR
PDFs escaneados ou em imagem aparecem aqui até você fazer o OCR.|Scanned or image-only PDFs appear here until you run OCR on them.
Clique na estrela de um PDF para ele aparecer aqui.|Click the star on a PDF to make it appear here.
Nenhum PDF com OCR|No PDFs with OCR
Os arquivos criados pelo OCR aparecem aqui.|Files created by OCR appear here.
Nada recente|Nothing recent
Os PDFs abertos ou alterados nos últimos 7 dias aparecem aqui.|PDFs opened or changed in the last 7 days appear here.
Pasta vazia|Empty folder
Nenhuma pasta|No folders
Crie pastas para organizar seus PDFs, por cliente ou por processo.|Create folders to organize your PDFs, for example by client or by case.
Importe PDFs pela tela inicial ou arraste-os para esta janela.|Import PDFs from the home screen or drag them into this window.
Use “Adicionar PDFs”, acima, ou arraste PDFs para esta janela.|Use “Add PDFs” above, or drag PDFs into this window.
Adicionar PDFs…|Add PDFs…
Adicionar PDFs|Add PDFs
Adicionar mais PDFs|Add more PDFs
Importar do computador…|Import from this computer…
Converter em PDF aqui…|Convert to PDF here…
Fazer OCR de todos|Run OCR on all
Tente outro termo.|Try another term.
Tirar da lista|Remove from list
Favoritar|Add to Favorites
Remover dos favoritos|Remove from Favorites
Adicionado aos Favoritos.|Added to Favorites.
Removido dos Favoritos.|Removed from Favorites.
Alteração desfeita.|Change undone.
Não há alteração para desfazer.|There is no change to undo.
Não há alteração para desfazer neste PDF.|There is no change to undo in this PDF.
Desfazer a última alteração?|Undo the last change?
Abrir no leitor|Open in reader
Abrir no leitor de PDF|Open in PDF reader
Copiar arquivo|Copy file
Arquivo copiado. Cole com Ctrl+V onde quiser.|File copied. Paste it anywhere with Ctrl+V.
Esse PDF já está na biblioteca.|This PDF is already in the library.
Esses PDFs já estão na biblioteca.|These PDFs are already in the library.
O PDF foi movido ou apagado.|The PDF was moved or deleted.
PDF não encontrado|PDF not found
O arquivo foi movido ou apagado.|The file was moved or deleted.
Não foi possível concluir|Couldn’t finish
Não foi possível converter|Couldn’t convert
Alguns arquivos não foram convertidos|Some files were not converted
Salvando…|Saving…
Salvar a nova ordem?|Save the new order?
Descartar|Discard
Continuar editando|Keep editing
Girar para a esquerda|Rotate left
Girar para a direita|Rotate right
Excluir páginas (Delete)|Delete pages (Delete)
Desfazer (Ctrl+Z)|Undo (Ctrl+Z)
Arraste para mudar a ordem|Drag to change the order
Ver a página grande (Espaço)|View large page (Space)
Extraindo…|Extracting…
Combinando…|Combining…
Dividindo…|Splitting…
Incluindo…|Inserting…
Removendo…|Removing…
Numerando…|Numbering…
Assinando…|Signing…
Copiando…|Copying…
Verificando…|Checking…
Conferindo o certificado…|Checking the certificate…
Procurando no Windows…|Searching in Windows…
Preparando a prévia…|Preparing the preview…
Corrigindo as páginas…|Fixing the pages…
Todas as páginas|All pages
Páginas ímpares (1, 3, 5…)|Odd pages (1, 3, 5…)
Páginas pares (2, 4, 6…)|Even pages (2, 4, 6…)
Escolher páginas…|Choose pages…
Página inteira|Whole page
Margens automáticas|Automatic margins
Aplicar a|Apply to
Primeiro número|First number
Tamanho da letra|Font size
Distância da borda|Distance from the edge
Começar a numerar na página|Start numbering on page
Dividir|Split
Número de partes|Number of parts
No início|At the start
No fim|At the end
Incluir|Insert
Extrair|Extract
Combinar|Combine
Escolher PDFs|Choose PDFs
Do computador…|From this computer…
Subir|Move up
Descer|Move down
Nome do novo PDF|New PDF name
Antes|Before
Depois|After
Em quantas partes você quer dividir?|How many parts do you want to split it into?
Escolha pelo menos 2 partes.|Choose at least 2 parts.
O PDF precisa ter pelo menos 2 páginas para ser dividido.|The PDF needs at least 2 pages to be split.
Corrigir e criar cópia|Fix and create copy
Assinatura digital|Digital signature
Certificado digital A1|A1 digital certificate
Certificado A1 ou A3|A1 or A3 certificate
Certificado A3 (token ou cartão)|A3 certificate (token or card)
Senha do certificado|Certificate password
Senha do certificado A1|A1 certificate password
Adicionar A1…|Add A1…
Adicionar outro certificado A1…|Add another A1 certificate…
Adicionar certificado A1 (.pfx/.p12)…|Add A1 certificate (.pfx/.p12)…
Procurar de novo (token conectado agora)|Search again (token connected now)
Procurar certificados no Windows|Search for certificates in Windows
Certificados encontrados no Windows|Certificates found in Windows
Nenhum certificado encontrado|No certificate found
Nenhum certificado digital|No digital certificate
Remover o certificado?|Remove the certificate?
Certificado removido do Prumo.|Certificate removed from Prumo.
Nenhum certificado A1 salvo no Prumo.|No A1 certificate saved in Prumo.
Mostrar a assinatura na página (carimbo)|Show the signature on the page (stamp)
Motivo (opcional). Ex.: Sou o autor deste documento|Reason (optional). E.g.: I am the author of this document
Proteção do documento|Document protection
Proteção do PDF assinado|Signed PDF protection
Nível padrão ao assinar|Default level when signing
Assinar no nível 1|Sign at level 1
Este certificado está vencido: a assinatura não será aceita como válida.|This certificate has expired: the signature will not be accepted as valid.
 (vencido)| (expired)
Quais páginas? Deixe em branco para incluir todas, ou digite, por exemplo: 3, 5-15, 20-fim|Which pages? Leave blank to include all, or type, for example: 3, 5-15, 20-end
Quais páginas corrigir? Deixe em branco para todas, ou digite, por exemplo: 1, 3-5|Which pages to fix? Leave blank for all, or type, for example: 1, 3-5
Clique nas páginas, arraste o mouse sobre várias ou digite, por exemplo: 1, 3-5, 10-fim. Dois cliques mostram a página grande.|Click pages, drag the mouse over several, or type, for example: 1, 3-5, 10-end. Double-click shows the large page.
Clique para marcar; dois cliques mostram a página grande|Click to select; double-click shows the large page
Clique nos PDFs ou arraste sobre eles|Click the PDFs or drag over them
Aparece em “Abrir com” nos PDFs|Appears in “Open with” on PDFs
Dica: misture letras, números e símbolos (ex.: Caso2026!Ana).|Tip: mix letters, numbers and symbols (e.g. Case2026!Ana).
O arquivo vai para a Lixeira do Windows. Dá para recuperar por lá, se precisar.|The file goes to the Windows Recycle Bin. You can recover it from there if needed.
A pasta e o PDF dentro dela vão para a Lixeira do Windows.|The folder and the PDF inside it go to the Windows Recycle Bin.
A pasta e os {} PDFs dentro dela vão para a Lixeira do Windows.|The folder and the {} PDFs inside it go to the Windows Recycle Bin.
Excluir pasta|Delete folder
Renomear pasta|Rename folder
Nova subpasta|New subfolder
Mover para pasta|Move to folder
Outra pasta…|Another folder…
Compartilhar|Share
Atual|Current
Texto digital|Digital text
Já tem OCR|Already has OCR
Já tem texto|Already has text
Sem páginas|No pages
Misto|Mixed
Vazio|Empty
Com senha|Password-protected
Pede a senha|Asks for the password
Cria uma cópia sem senha|Creates a copy without a password
Esqueceu a senha do Prumo?|Forgot the Prumo password?
Ler qual PDF?|Read which PDF?
Fazer OCR de quais PDFs?|Run OCR on which PDFs?
Organizar qual PDF?|Organize which PDF?
Incluir páginas em qual PDF?|Insert pages into which PDF?
Remover páginas de qual PDF?|Remove pages from which PDF?
Extrair páginas de qual PDF?|Extract pages from which PDF?
Dividir qual PDF?|Split which PDF?
Cortar ou girar páginas de qual PDF?|Crop or rotate pages of which PDF?
Numerar as páginas de qual PDF?|Number the pages of which PDF?
Assinar qual PDF?|Sign which PDF?
Excluir “{}”?|Delete “{}”?
Excluir {} PDFs?|Delete {} PDFs?
Mover {} PDFs|Move {} PDFs
{} selecionado|{} selected
{} selecionados|{} selected
Última cópia: {}.|Last backup: {}.
PDF importado: {}|PDF imported: {}
{} PDFs importados.|{} PDFs imported.
PDF criado: {}|PDF created: {}
{} PDFs criados|{} PDFs created
OCR concluído: {}|OCR finished: {}
“{}” entrou na fila do OCR.|“{}” was added to the OCR queue.
Cópia criada: {}|Copy created: {}
Movido para {}.|Moved to {}.
PDF combinado: {}|Combined PDF: {}
PDF assinado: {}|PDF signed: {}
Certificado adicionado: {}|Certificate added: {}
Novo PDF: {}|New PDF: {}
{} - Parte {}|{} - Part {}
{} - corrigido|{} - fixed
{} - protegido|{} - protected
{} - sem senha|{} - no password
 - protegido| - protected
 - resumo| - summary
{} assinaturas|{} signatures
1 assinatura|1 signature
Resumo de “{}”|Summary of “{}”
Trecho extraído|Extracted excerpt
Selecione um trecho com texto para adicionar ao resumo.|Select a piece of text to add to the summary.
{} · modo leitor|{} · reader mode
Destacar em {}|Highlight in {}
Amarelo|Yellow
Verde|Green
Azul|Blue
Rosa|Pink
Laranja|Orange
Nada para destacar.|Nothing to highlight.
Desfeito: {}.|Undone: {}.
Refeito: {}.|Redone: {}.
Página anterior (←)|Previous page (←)
Próxima página (→)|Next page (→)
Diminuir (−)|Zoom out (−)
Ampliar (+)|Zoom in (+)
Fechar (Esc)|Close (Esc)
A página parece estar em branco.|The page seems to be blank.
Sem giro a aplicar.|No rotation to apply.
Giro a aplicar: {}°|Rotation to apply: {}°
Nada mudou: arraste a moldura, digite as margens ou gire a página.|Nothing changed: drag the frame, type the margins or rotate the page.
Arraste a moldura azul na página ou digite as margens.|Drag the blue frame on the page or type the margins.
Os números que o Prumo tinha gravado antes nessa posição foram trocados pelos novos.|The numbers Prumo had written before at that position were replaced by the new ones.
1 página numerada.|1 page numbered.
{} páginas numeradas.|{} pages numbered.
Use “Desfazer última alteração” se precisar.|Use “Undo last change” if you need to.
Páginas reorganizadas. Use “Desfazer última alteração” se precisar.|Pages reorganized. Use “Undo last change” if you need to.
Senha incorreta. Tente de novo (maiúsculas e minúsculas fazem diferença).|Wrong password. Try again (upper and lower case matter).
Este PDF está protegido. Digite a senha para abrir.|This PDF is protected. Type the password to open it.
Este PDF tem senha. Para fazer OCR, organizar ou dividir, crie antes uma cópia sem senha.|This PDF has a password. To run OCR, organize or split it, first create a copy without a password.
Este PDF tem senha. Para numerar, crie antes uma cópia sem senha.|This PDF has a password. To number it, first create a copy without a password.
Este PDF tem senha. Para cortar ou girar, crie antes uma cópia sem senha.|This PDF has a password. To crop or rotate it, first create a copy without a password.
PDF com senha não pode ser assinado. Remova a senha antes (“Remover senha”).|A password-protected PDF can’t be signed. Remove the password first (“Remove password”).
Esses PDFs já têm texto selecionável. O OCR não é necessário.|These PDFs already have selectable text. OCR is not needed.
Todas as páginas já têm texto selecionável. O OCR não é necessário.|All pages already have selectable text. OCR is not needed.
Este arquivo já é o resultado de um OCR.|This file is already the result of an OCR.
O OCR deste PDF já está em andamento.|OCR for this PDF is already in progress.
Espere o OCR deste PDF terminar para organizar as páginas.|Wait for OCR on this PDF to finish before organizing its pages.
Espere o OCR terminar antes de mudar a pasta da biblioteca.|Wait for OCR to finish before changing the library folder.
PDF com assinatura digital|PDF with a digital signature
Fazer OCR cria uma cópia sem a assinatura digital. O arquivo original continua assinado e válido. Fazer o OCR mesmo assim?|Running OCR creates a copy without the digital signature. The original file stays signed and valid. Run OCR anyway?
Cópia com OCR criada|OCR copy created
Tudo é processado neste computador. O Prumo PDF não coleta dados e não envia arquivos para a internet; só sai do computador o que você compartilhar ou o que a sua nuvem sincronizar.|Everything is processed on this computer. Prumo PDF doesn’t collect data and doesn’t send files to the internet; only what you share, or what your cloud syncs, leaves the computer.
Os PDFs ficam na pasta da biblioteca, visível no Explorador de Arquivos.|PDFs stay in the library folder, visible in File Explorer.
O OCR usa o Tesseract e roda inteiramente neste computador. Páginas com baixa confiança são marcadas para revisão; mesmo assim, confira nomes, datas, números e valores no original.|OCR uses Tesseract and runs entirely on this computer. Low-confidence pages are flagged for review; even so, check names, dates, numbers and amounts against the original.
Marque até %d. Idiomas demais juntos deixam o OCR mais lento e menos preciso.|Select up to %d. Too many languages at once make OCR slower and less accurate.
A mudança vale na próxima vez que você abrir o Prumo.|The change takes effect the next time you open Prumo.
A mudança vale na próxima vez que você abrir o Prumo. A tradução para este idioma ainda precisa de revisão por quem o fala.|The change takes effect the next time you open Prumo. The translation for this language still needs review by a speaker of it.
Depois de assinado, o PDF não pode mais ser alterado: qualquer mudança (destaque, corte, numeração, páginas) invalida a assinatura. Por isso o Prumo assina uma cópia, “{name}”, e o original continua como está, para você editar se precisar.|Once signed, the PDF can no longer be changed: any change (highlight, crop, numbering, pages) invalidates the signature. That is why Prumo signs a copy, “{name}”, and the original stays as it is, so you can edit it if needed.
""".strip().splitlines()


def main():
    out = Path(__file__).resolve().parent.parent / "app" / "locales"
    out.mkdir(parents=True, exist_ok=True)
    cats = {c: {} for c in COLS}
    for ln in MORE:
        pt, en = ln.split("|", 1)
        cats["en"][pt] = en
    for ln in CORE:
        cells = ln.split("|")
        assert len(cells) == 1 + len(COLS), (len(cells), ln)
        pt = cells[0]
        for c, v in zip(COLS, cells[1:]):
            if v.strip():
                cats[c][pt] = v
    for c, cat in cats.items():
        (out / f"{c}.json").write_text(json.dumps(cat, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        print(c, len(cat))


if __name__ == "__main__":
    main()
