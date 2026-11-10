# Caixa Simples

PDV nativo para GNOME, em Python, GTK 4, Libadwaita e SQLite. Funciona localmente, sem servidor, conta ou internet. Licença GPL-3.0-or-later.

## Usar

Abra **Vender** e passe o produto no leitor USB em modo teclado/HID, com Enter ao final. Um código novo abre o cadastro de nome e preço. Leituras repetidas aumentam a quantidade. Também é possível digitar o código e pressionar Enter.

Em **Produtos**, pesquise por nome ou código e use o lápis para editar. O preço novo vale para próximas inclusões no carrinho; vendas anteriores conservam os valores e nomes originais.

Finalize, escolha Dinheiro, PIX ou Cartão e clique em **Concluir e imprimir**. No dinheiro, informar o recebido é opcional. A venda é gravada antes de gerar/enviar o PDF. Cancelar a impressão não cancela a venda. O comprovante salvo pode ser consultado em **Menu → Vendas recentes**, com reimpressão e exportação PDF sem gerar outra venda.

A aba **Fechamento** mostra as unidades vendidas no dia, a quantidade de produtos diferentes e o número de vendas concluídas. A lista apresenta os produtos mais vendidos primeiro, com suas quantidades. Clique em **Hoje** para escolher outro dia no calendário; **Voltar para hoje** retoma o acompanhamento do dia atual. Os números são calculados automaticamente a partir das vendas já salvas, inclusive as anteriores a esta atualização. Não é preciso executar uma ação de fechamento nem zerar contadores. Carrinhos ainda não concluídos não entram na lista. A tela acompanha a mudança de dia quando estiver em Hoje; consultas a datas anteriores permanecem na data escolhida.

**Não emite documentos fiscais.** Os papéis são identificados como comprovantes não fiscais.

## Instalar pelo Flatpak

Para baixar a versão pronta e transferir seus dados, siga o [passo a passo de instalação](INSTALACAO.md).

Se recebeu `CaixaSimples.flatpak`, abra-o no instalador de aplicativos, ou execute uma vez:

```sh
flatpak install --user ./CaixaSimples.flatpak
flatpak run io.github.caixasimples.CaixaSimples
```

O runtime GNOME 50 precisa estar instalado; o instalador poderá oferecer seu download. O uso cotidiano funciona sem rede. O aplicativo aparece no menu como **Caixa Simples**.

Para construir pelo manifesto com `flatpak-builder`:

```sh
flatpak-builder --user --install --force-clean _build io.github.caixasimples.CaixaSimples.json
```

Alternativa sem flatpak-builder, quando `org.gnome.Sdk//50` e `org.gnome.Platform//50` já estão disponíveis:

```sh
./scripts/build-flatpak.sh
```

O script exige diretórios de construção/repositório ainda não existentes. Outros caminhos podem ser passados como primeiro e segundo argumentos. O manifesto também pode ser aberto no GNOME Builder. Não há permissão de rede nem acesso geral ao diretório pessoal: arquivos são escolhidos pelos portais nativos.

## Executar o código-fonte

Dependências: Python ≥ 3.10, PyGObject, Pycairo, introspecção GTK ≥ 4.14, Libadwaita ≥ 1.5, Pango/Cairo e um ambiente gráfico GTK. Use o Python do sistema, que encontra os módulos de introspecção. No Fedora, os pacotes são `python3-gobject`, `python3-cairo`, `gtk4`, `libadwaita` e `meson`; no Debian/Ubuntu, `python3-gi`, `python3-gi-cairo`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`, `meson` e `ninja-build` (verifique as versões mínimas).

Na pasta do projeto:

```sh
./caixa-simples
```

Para instalar nativamente para seu usuário:

```sh
meson setup build-local --prefix="$HOME/.local"
meson install -C build-local
```

Para instalação do sistema, use `meson setup build --prefix=/usr` e `sudo meson install -C build`. Depois da instalação, basta usar o menu de aplicativos, sem terminal. Não é preciso instalar cabeçalhos de desenvolvimento C para este projeto Python.

## Impressão

Em **Preferências**, configure nome da loja, rodapé e bobina de 58 ou 80 mm. **Selecionar impressora** abre o diálogo nativo GTK/CUPS ou seu portal no Flatpak. A seleção é reutilizada nesta sessão; preferências de impressão serializáveis ficam no banco e são sugeridas na próxima abertura, que exige nova seleção. O aplicativo não promete impressão direta entre reinicializações. Alterar a bobina invalida a seleção em memória.

O comprovante é PDF vetorial, com texto Pango, quebra de nomes longos, largura física da bobina e altura variável. Verifique também o papel suportado na configuração da impressora: alguns drivers térmicos precisam de ajuste de escala/comprimento. O retorno de sucesso significa que o sistema aceitou o trabalho; CUPS pode reportar falta de papel ou falha física posteriormente. Reimprima pelo histórico quando necessário.

**Testar impressão** gera um comprovante explicitamente marcado como teste, sem salvar venda. **Salvar PDF** usa o seletor nativo; **Visualizar PDF** abre o visualizador instalado. Não é necessário ter impressora para registrar vendas.

Veja [TESTES.md](TESTES.md) para verificações executadas e roteiro de teste físico/portal.

## Dados e recuperação

O banco é resolvido por `GLib.get_user_data_dir()/io.github.caixasimples.CaixaSimples/caixa.sqlite3`. Na instalação tradicional costuma ficar em `~/.local/share/io.github.caixasimples.CaixaSimples/`; no Flatpak, dentro do diretório persistente da aplicação. Não fica no código-fonte nem na instalação. PDFs de trabalho ficam no cache e são regenerados a partir do histórico.

Os valores são inteiros em centavos, com transações, chaves estrangeiras, WAL, sincronização FULL, restrições e versão de migração (`user_version=1`). O token único por carrinho impede registrar duas vezes a mesma conclusão. Nomes, preços, loja e rodapé são preservados no momento da venda.

São feitas cópias consistentes pela API SQLite ao abrir, a cada 15 minutos, ao encerrar e antes de restaurar; ficam em `backups/`, ao lado do banco, limitadas às dez últimas. Para proteger contra falha do computador, use **Exportar backup** e guarde em outro dispositivo.

**Restaurar backup** valida formato, integridade e totais, solicita confirmação e preserva os dados atuais antes de substituir. O carrinho não concluído é descartado após uma restauração confirmada. Falhas de abertura mostram uma tela de recuperação: **Restaurar backup** preserva o banco original e os arquivos WAL/SHM em uma pasta `dados-preservados-…` antes de recuperar. Não exclua esses arquivos ao buscar suporte.

## Estrutura

- `caixa_simples/core.py`: produtos, carrinho, cálculos, resumo diário, banco e backups.
- `caixa_simples/ui.py`: telas e diálogos nativos, histórico e recuperação.
- `caixa_simples/receipt.py`: comprovantes PDF e integração real `Gtk.PrintDialog`.
- `data/`: lançador, metadados AppStream e ícone vetorial próprio.
- `meson.build` e manifesto JSON: instalação e distribuição.
- `tests/`, `scripts/smoke_ui.py` e `scripts/acceptance_ui.py`: testes de lógica e de interface.

O identificador `io.github.caixasimples.CaixaSimples` é provisório: antes de publicar, substitua-o pelo domínio/identificador controlado pelo mantenedor em todos os arquivos. O projeto não afirma vínculo com GNOME Circle. Os metadados ainda não têm homepage oficial; isso gera um aviso conhecido do validador AppStream.


## Identidade visual

O ícone mantém o desenho simples de um comprovante sobre uma gaveta azul, com bordas iluminadas, rebaixo e sombra de contato suaves. É um SVG original em grade de 128 × 128 px, com base em 112 px, perfil inferior de 4 px, paleta GNOME e formas simples sem sombras externas. A versão simbólica em 16 × 16 px é monocromática e recebe a cor do tema pelo GTK. Ambos são instalados no tema hicolor pelo Meson e incluídos no Flatpak.

Referências: [GNOME HIG — App Icons](https://developer.gnome.org/hig/guidelines/app-icons.html) e [UI Icons](https://developer.gnome.org/hig/guidelines/ui-icons.html). A arte não implica participação ou certificação no GNOME Circle.
