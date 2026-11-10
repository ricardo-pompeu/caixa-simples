# Instalar o Caixa Simples em outro computador

O pacote pronto é para **Linux de 64 bits (x86_64)**, como a maioria dos computadores Intel e AMD. No terminal, `uname -m` deve mostrar `x86_64`. Para Linux ARM, veja as instruções de compilação no [README](README.md).

1. Instale o Flatpak, se ainda não estiver disponível. No Fedora: `sudo dnf install flatpak`. No Ubuntu ou Debian: `sudo apt install flatpak`.
2. Abra a [página da versão 0.2.1 no GitHub](https://github.com/ricardo-pompeu/caixa-simples/releases/tag/v0.2.1). Em **Assets**, baixe **CaixaSimples.flatpak**. Como o repositório é privado, entre no GitHub com uma conta que tenha acesso.
3. Abra o terminal na pasta onde salvou o arquivo. Adicione o Flathub, instale o ambiente GNOME 50 e, por fim, instale o pacote:

   ```sh
   flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
   flatpak install --user flathub org.gnome.Platform//50
   flatpak install --user ./CaixaSimples.flatpak
   ```

4. Abra **Caixa Simples** no menu de aplicativos. Se preferir, execute `flatpak run io.github.caixasimples.CaixaSimples`.

A primeira instalação do ambiente GNOME precisa de internet. O aplicativo funciona offline depois disso. Se quiser conferir o arquivo baixado, salve também `SHA256SUMS` na mesma pasta e rode `sha256sum -c SHA256SUMS` antes de instalar.

## Levar os dados do computador antigo

1. Na máquina antiga, finalize qualquer venda em andamento. No menu do Caixa Simples, escolha **Exportar backup**.
2. Copie o arquivo exportado para a outra máquina, por exemplo com um pendrive. Ele contém os produtos, as vendas e as preferências; guarde-o como um arquivo privado da loja.
3. Na máquina nova, abra o aplicativo, escolha **Restaurar backup**, selecione a cópia e confirme. A restauração substitui os dados atuais da máquina nova. Confira os produtos e as vendas recentes antes de começar a operar.
4. Se usar impressora, selecione-a em **Preferências** e faça uma impressão de teste.

O backup é uma cópia do momento da exportação. Os dois computadores não sincronizam vendas ou alterações automaticamente.
