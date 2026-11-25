# Oscillo Control クイックガイド

## Firefox で接続する

1. [J-LAN ポータル](http://10.105.50.22/) または [E16 ポータル](http://192.168.19.64/) の **Monitors → Oscilloscope control** を開きます。認証画面が出たら、既存の **E88 DAQ Control** のログイン情報を使います。e88evb01 本体からは [localhost の操作画面](http://127.0.0.1:8765/) も開けます。
2. 上部で **Oscilloscope 01** を選び、**Connected** と本体画面が出ることを確認します。**Live display** をオンにすると本体画面が自動更新されます。

## 操作を有効にする

1. **Enable control** を押します。**Control enabled** と表示され、設定や取得の操作ができるようになります。
2. 操作を終えたら **Disable control** を押します。**Viewing only** に戻り、本体画面と波形の閲覧を続けられます。ページを再読み込みした場合も **Viewing only** から始まります。

## スケールや位置を変える

| 項目 | 操作 |
| --- | --- |
| **Vertical → Scale (V/div)** | **CH1**〜**CH4** から対象を選び、例として `0.5` を入力して **Apply** または Enter。`0.5` は 500 mV/div です。 |
| **Vertical → Position (V)** | 選んだチャンネルの縦位置を V で指定し、**Apply** または Enter。 |
| **Horizontal → Scale (s/div)** | 全チャンネル共通の時間軸です。20 ns/div なら `2e-8`、1 µs/div なら `1e-6` を入力して **Apply** または Enter。 |
| **Horizontal → Position (s)** | 時間軸での位置を秒で指定し、**Apply** または Enter。 |
| **Acquisition** | **Run** で連続取得、**Stop** で停止、**Single** で次のトリガを待って1回取得します。 |
| **Trigger** | **Source**、**Mode**、**Slope** は選択すると反映します。**Level (V)** は入力して **Apply** または Enter。 |

`−`・`+` やノブ上のマウスホイールでも、その項目を一段ずつ変更できます。操作後、本体から読み戻した値が入力欄と画面下部のメッセージに表示されます。チャンネル表示は **Show selected channel** で切り替えます。

## 反応しないとき

- **Viewing only** のときに設定を変えるには、**Enable control** を押してください。
- **Unavailable** が出たら、対象のオシロの電源とソケットサーバーを確認して、上部の **Connect** を押してください。オシロ本体との通信には TCP `3000` を使います。
- **Settings read failed** が出たら、上部の **Connect** で本体の現在値を読み直してください。
- 波形データを見る場合は、対象のチャンネルを選び、**Waveform samples** の **Capture CHn** を押します。**Download CSV** で保存できます。
