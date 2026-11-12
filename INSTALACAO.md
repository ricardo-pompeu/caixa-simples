# Instalar o Bipe em outro computador

## Instalação automática com a POS-80 USB

Baixe o kit `Bipe-POS80-linux-x86_64.tar.gz` nos **Assets** da [versão 0.3.0](https://github.com/ricardo-pompeu/caixa-simples/releases/tag/v0.3.0). Ele inclui o Bipe, o instalador e o checksum. O repositório é privado e requer uma conta com acesso.

1. Copie o kit para o computador novo e extraia o arquivo.
2. Ligue a **POS-80** e conecte o cabo USB.
3. Abra o terminal na pasta extraída e execute, como o usuário que vai operar o caixa:

   ```sh
   sh instalar-caixa-simples.sh
   ```

4. Autorize o administrador do Linux quando solicitado. O instalador usa o driver **Generic Text-Only Printer** (`cups-filters`), detecta o endereço USB da impressora nesta máquina, cria a fila de texto contínuo de 80 mm e instala o Flatpak para o usuário atual. Em Fedora, Ubuntu e Debian, instala os pacotes faltantes quando necessário. Se o GNOME 50 ainda não estiver disponível, baixa o runtime do Flathub.
5. Abra **Bipe** e deixe **Detectar térmica automaticamente** em **Preferências → Impressora**. Use **Testar impressão** para confirmar que o comprovante sai correto. Isso não registra uma venda.

O instalador reaproveita uma fila POS-80 que já esteja correta. Em caso de conflito com outra fila ou com mais de uma POS-80 conectada, ele explica o problema e preserva a configuração existente. Ele não altera a impressora padrão nem copia o número de série, os dados da loja ou as preferências do notebook. O procedimento requer CUPS com suporte a drivers PPD legados; as etapas de instalação de dependências precisam de rede.

Se o app já estiver instalado, execute `sh instalar-caixa-simples.sh --so-impressora` para preparar apenas a fila. Para verificar a conexão e a fila sem alterar nada, use `sh instalar-caixa-simples.sh --verificar`.

## Instalação manual, sem preparação da impressora

O pacote pronto é para **Linux de 64 bits (x86_64)**, como a maioria dos computadores Intel e AMD. No terminal, `uname -m` deve mostrar `x86_64`. Para Linux ARM, veja as instruções de compilação no [README](README.md).

1. Instale o Flatpak, se ainda não estiver disponível. No Fedora: `sudo dnf install flatpak`. No Ubuntu ou Debian: `sudo apt install flatpak`.
2. Abra a [página da versão 0.3.0 no GitHub](https://github.com/ricardo-pompeu/caixa-simples/releases/tag/v0.3.0). Em **Assets**, baixe **Bipe.flatpak**. Como o repositório é privado, entre no GitHub com uma conta que tenha acesso.
3. Abra o terminal na pasta onde salvou o arquivo. Adicione o Flathub, instale o ambiente GNOME 50 e, por fim, instale o pacote:

   ```sh
   flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
   flatpak install --user flathub org.gnome.Platform//50
   flatpak install --user ./Bipe.flatpak
   ```

4. Abra **Bipe** no menu de aplicativos. Se preferir, execute `flatpak run io.github.caixasimples.CaixaSimples`.

A primeira instalação do ambiente GNOME precisa de internet. O aplicativo funciona offline depois disso. Se quiser conferir o arquivo baixado, salve também `SHA256SUMS` na mesma pasta e rode `sha256sum -c SHA256SUMS` antes de instalar.

## Levar os dados do computador antigo

1. Na máquina antiga, finalize qualquer venda em andamento. No menu do Bipe, escolha **Exportar backup**.
2. Copie o arquivo exportado para a outra máquina, por exemplo com um pendrive. Ele contém os produtos, as vendas e as preferências; guarde-o como um arquivo privado da loja.
3. Na máquina nova, abra o aplicativo, escolha **Restaurar backup**, selecione a cópia e confirme. A restauração substitui os dados atuais da máquina nova. Confira os produtos e as vendas recentes antes de começar a operar.
4. Se usar impressora, selecione-a em **Preferências** e faça uma impressão de teste.

O backup é uma cópia do momento da exportação. Os dois computadores não sincronizam vendas ou alterações automaticamente.
