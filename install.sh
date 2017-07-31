#!/usr/bin/sh

echo "Installing and updating FASTBUILD"

git pull origin master
mkdir -p /usr/local/share/fastbuild
cp -f fastbuild.py /usr/local/share/fastbuild/fastbuild.py
chmod +x /usr/local/share/fastbuild/fastbuild.py
ln -s -f /usr/local/share/fastbuild/fastbuild.py /usr/bin/fastbuild

echo ""
echo "Done."
echo ""
echo "Now you can use fastbuild by typing command \"fastbuild\" in directory where build config file exists."