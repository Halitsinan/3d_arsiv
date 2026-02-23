Yeni bilgisayarda kurulum için:

git clone git@github.com:Halitsinan/3d_arsiv.git
cd 3d_arsiv
sudo bash setup.sh
# sonra service_account.json dosyasını manuel kopyala


Bundan sonra her değişiklikten sonra:
cd /home/hsa/3d_asset_manager/app
git add .
git commit -m "değişiklik açıklaması"
git push
