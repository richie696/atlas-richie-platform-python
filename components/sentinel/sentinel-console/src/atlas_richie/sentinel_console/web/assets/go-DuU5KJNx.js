const n=`---
title: Go：公式 Sentinel SDK の接続
summary: Go ネイティブのフィールドを使ってください。Java の JSON をそのままコピーはしません。
prerequisite: Go 1.23 以降。リポジトリに実行可能な Go demo があること
outcome: ルールの読込が成功し、リクエストが拒否され、観測の上報まで接続されます
---

## 依存関係と実行

demo は公式の sentinel-golang と Nacos Go SDK を使います。こちらも相互運用デモです。起動はテストを先に実行してから直接起動します。

\`\`\`bash

go test ./...
go run .
\`\`\`

> **注記** demo の既定の待ち受けは 127.0.0.1:18082 で、DEMO_PORT と DEMO_BIND_HOST で変更できます。起動に成功すると go-demo listening on host; rule source key=… と表示されます。

## 設定項目：アドレスが 2 つの変数に分割されている

Go 側ではアドレスがホストとポートの 2 つの変数に分かれており、Java とは書き方が違います。言語をまたぐ接続で最初につまずく点がここです。

| 変数                 | 既定値                                   | 説明                                                                                     |
| :------------------- | :--------------------------------------- | :--------------------------------------------------------------------------------------- |
| NACOS_SERVER_ADDR    | 127.0.0.1                                | ホスト名だけを入れます。ポートは付けません                                               |
| NACOS_SERVER_PORT    | 8848                                     | ポートは独立した変数                                                                     |
| NACOS_NAMESPACE      | public                                   | namespace ID                                                                             |
| NACOS_GROUP          | DEFAULT_GROUP                            | グループ                                                                                 |
| NACOS_DATA_ID        | sentinel-e2e-20261017-go-flow-rules.json | Data ID                                                                                  |
| NACOS_USERNAME       | nacos                                    | アカウント                                                                               |
| NACOS_PASSWORD       | 既定値なし                               | 認証を有効にする場合は必須                                                               |
| NACOS_AUTH_ENABLED   | true                                     | false にするとアカウントとパスワードを省略できます                                       |
| RULE_SOURCE_PROVIDER | nacos                                    | nacos または consul。空欄でも nacos として扱われます。ほかの値は起動時にエラーになります |
| RULE_SOURCE_PROFILE  | native-array-v1                          | managed-envelope-v1 も指定可                                                             |
| RULE_BINDING_ID      | 既定値なし                               | マネージドエンベロープと読込観測に必須                                                   |
| RULE_PROFILE_ID      | sentinel-go-v1                           | コンソールのバインディングと一致させる必要があります                                     |

> **注記** 3 つの言語とも RULE_SOURCE_PROVIDER を空欄にすると nacos に戻ります。認識できない値を入れると起動時にエラーになります。

## ルールを 1 件書く

Go SDK のルールフィールドは Java と異なります。リソース名はいずれも GET /api/hello です。

\`\`\`json
[
  {
    "resource": "GET /api/hello",
    "threshold": 3,
    "tokenCalculateStrategy": 0,
    "controlBehavior": 0,
    "relationStrategy": 0,
    "statIntervalInMs": 1000
  }
]
\`\`\`

| フィールド             | 指定する値           | 意味                                                                     |
| :--------------------- | :------------------- | :----------------------------------------------------------------------- |
| resource               | 計測点と一字一句一致 | 保護対象のリソース                                                       |
| threshold              | 正の整数             | しきい値                                                                 |
| statIntervalInMs       | 1000                 | 統計ウィンドウ。固定 1 秒。現在の profile が対応する唯一のウィンドウです |
| tokenCalculateStrategy | 0                    | 計算戦略。0 は直接計算                                                   |
| relationStrategy       | 0                    | 関連戦略。0 は現在のリソース基準                                         |
| controlBehavior        | 0                    | 制御動作。0 は即時拒否                                                   |

> **注記** Go のしきい値フィールドは count ではなく threshold です。Java のルール JSON をそのまま写すとフィールド名が合わず、スナップショット全体が拒否されます。

## Reporter を接続する

Go は PKCS#12 ではなく PEM 形式の証明書と秘密鍵を使います。Java と Go・Rust の間で 2 番目につまずきやすい点がここです。

| 変数                  | 説明                        |
| :-------------------- | :-------------------------- |
| METRICS_COLLECTOR_URL | Collector の HTTPS アドレス |
| METRICS_REPORTER_ID   | 登録済みの Reporter 識別子  |
| METRICS_CLIENT_CERT   | PEM のクライアント証明書    |
| METRICS_CLIENT_KEY    | PEM のクライアント秘密鍵    |
| METRICS_COLLECTOR_CA  | Collector の CA バンドル    |

> **注記** Java は METRICS_CLIENT_PKCS12 と METRICS_CLIENT_PKCS12_PASSWORD、Go と Rust は METRICS_CLIENT_CERT と METRICS_CLIENT_KEY を使います。2 組の変数名は共通ではありません。

## 3 ステップの検証

Go demo の /rules は、有効なスナップショットをまだ読み込んでいない間 503 を返し、rules_loaded=false を示します。それ自体が有用な手がかりです。

1. /rules をリクエストし、rules_loaded=true かつ rule_count が 0 より大きいことを確認します。
2. /api/hello をリクエストし、429 blocked by Sentinel を確認します。
3. /api/delay?ms=250 をリクエストして遅延サンプルを作り、RT 指標を検証します。
4. コンソールに戻り、インスタンスの読込状態と概要の指標を確認します。

## よくある失敗箇所

Go demo の失敗点は Java と概ね同様ですが、引き金は 2 つに集中しています。アドレスの書き方と、ルールフィールド名が異なることです。次の表は「現象 → 原因 → 対処」の形でよくある問題をまとめます。

| 現象                                                                           | 原因                                                                                                                                                 | 対処                                                                                                                    |
| :----------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------------- |
| Nacos に接続できず、クライアントが繰り返し再試行する                           | NACOS_SERVER_ADDR に 127.0.0.1:8848 と誤って入力しています。Go 側ではこの変数はホスト名だけを受け付け、ポートは独立した変数です                      | 2 つの変数に分けます。NACOS_SERVER_ADDR=127.0.0.1 と NACOS_SERVER_PORT=8848                                             |
| ルールスナップショット全体が拒否され、コンソール側には前の内容が表示されたまま | Go のしきい値フィールドは count ではなく threshold です。Java のルール JSON をそのままコピーすると不明フィールドで全体を拒否されます                 | Go のフィールド名を使います。threshold、statIntervalInMs、tokenCalculateStrategy、relationStrategy、controlBehavior     |
| /rules が 503 と rules_loaded=false を返す                                     | 有効なスナップショットをまだ読み取れていない状態で、起動段階の正常な状態であり障害ではありません                                                     | 1 つのポーリング周期を待ってからリクエストします。503 が続く場合はアドレス・資格情報・Data ID を調べます                |
| 読込状態が不明と表示される                                                     | RULE_PROFILE_ID はコンソールのバインディングと一致する必要があり、Go は sentinel-go-v1 です。マネージドエンベロープでは RULE_BINDING_ID も必要です   | profile とバインディング識別子を揃えます。managed-envelope-v1 を使う場合はエンベロープ内の profile が同じ値か確認します |
| 指標が常に空                                                                   | Go は PEM の 3 点セット METRICS_CLIENT_CERT、METRICS_CLIENT_KEY、METRICS_COLLECTOR_CA を使います。Java の METRICS_CLIENT_PKCS12 と書いても効きません | PEM の 3 点セットに置き換え、METRICS_COLLECTOR_URL が設定され https であることを確認します                              |
| 起動直後に終了し、unsupported RULE_SOURCE_PROVIDER と表示される                | 正確な nacos または consul のみを受け付け、大文字小文字や別名の正規化は行わない                                                                      | 正確な値に書き換えます。Consul に切り替える場合は CONSUL_URL と CONSUL_KEY も指定します                                 |

> **注記** Go demo の /rules は有効なスナップショットがない間 503 を返します。「読めたかどうか」を判断する最も直接的な手がかりです。サービスの異常と扱わないでください。

## 公式ドキュメント

- [Sentinel Go](https://sentinelguard.io/zh-cn/docs/golang/flow-control.html)
`;export{n as default};
