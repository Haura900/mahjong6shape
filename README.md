# 6枚形 + 西西 受け入れ変化トレーナー

麻雀の1スート6枚形 + 西西を題材にした、静的ブラウザクイズゲームです。

## 公開方法

GitHub Pagesで、公開元をリポジトリルートに設定してください。

サーバーやDBは使いません。成績はブラウザの `localStorage` に、キー `sixShapeTrainerStats` で保存されます。

## ローカル確認

```powershell
python -m http.server 8765
```

その後、ブラウザで `http://127.0.0.1:8765/` を開きます。

## データ更新

`tree/6枚形変化木_nodes.csv` と `tree/6枚形変化木_directed_edges.csv` を更新した後、次を実行してください。

```powershell
python scripts/build_quiz_data.py
```

`quiz-data.json` が更新されます。
