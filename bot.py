on:
  workflow_dispatch:

jobs:
  run-bot:
    runs-on: ubuntu-latest
    timeout-minutes: 30  # чтобы job не висел вечно
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      - name: Run bot
        env:
          BOT_TOKEN: ${{ secrets.BOT_TOKEN }}
          ADMIN_CHAT_ID: ${{ secrets.ADMIN_CHAT_ID }}
        run: python bot.py
