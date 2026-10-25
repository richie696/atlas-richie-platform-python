---
title: Java：公式 SDK からコンソール表示まで
summary: 2 段階で接続します。ルール実行と実行観測です。
prerequisite: JDK 17 以降、Maven 3.9 以降。リポジトリに実行可能な Java demo があること
outcome: ルールが実際に遮断され、コンソールで指標と読込観測が見える状態になります
---

## 依存関係と実行

demo は公式の Sentinel Java Core と Nacos クライアントを使用します。相互運用を示すデモであり、本番向けのランタイムアダプタではありません。

ビルドと起動のコマンドは以下のとおりです。公式 README は classes と classpath を組み合わせる方式で、実行可能な jar は生成しません。

```bash

mvn -q package dependency:build-classpath -Dmdep.outputFile=target/classpath.txt
java -cp "target/classes:$(cat target/classpath.txt)" io.atlasrichie.sentinel.demo.JavaSentinelDemo
```

> **注記** demo の既定の待ち受けは 127.0.0.1:18081 で、DEMO_PORT と DEMO_BIND_HOST で変更できます。起動に成功すると java-demo listening on host:port; rule source=… と表示されます。

## 設定はすべて環境変数で渡す

この demo に設定ファイルはなく、application.properties も yml も存在しません。すべての設定は環境変数で渡します。以下はルールソースに関係する部分です。

| 変数                 | 既定値                                     | 説明                                                                   |
| :------------------- | :----------------------------------------- | :--------------------------------------------------------------------- |
| NACOS_SERVER_ADDR    | 127.0.0.1:8848                             | ホストとポートを 1 つにまとめます                                      |
| NACOS_NAMESPACE      | public                                     | namespace ID                                                           |
| NACOS_GROUP          | DEFAULT_GROUP                              | グループ                                                               |
| NACOS_DATA_ID        | sentinel-e2e-20261017-java-flow-rules.json | Data ID                                                                |
| NACOS_USERNAME       | nacos                                      | アカウント                                                             |
| NACOS_PASSWORD       | 既定値なし                                 | 認証を有効にする場合は必須。secret manager または shell から注入します |
| NACOS_AUTH_ENABLED   | true                                       | false にするとアカウントとパスワードを省略できます                     |
| RULE_SOURCE_PROVIDER | nacos                                      | nacos または consul。空欄でも nacos として扱われます                   |
| RULE_SOURCE_PROFILE  | native-array-v1                            | managed-envelope-v1 も指定可。その他の値は起動時にエラーになります     |
| RULE_BINDING_ID      | 既定値なし                                 | マネージドエンベロープと読込観測に必須                                 |
| RULE_PROFILE_ID      | sentinel-java-v1                           | コンソールのバインディングの profile と一致させる必要があります        |

> **注記** Consul に切り替える場合は設定項目が CONSUL_URL、CONSUL_KEY、CONSUL_DATACENTER、CONSUL_TOKEN に変わります。URL にトークンやクエリパラメータを含めることはできません。トークンは X-Consul-Token リクエストヘッダにのみ設定します。

## ルールを 1 件書く

設定センターには同型の JSON 配列を置きます。Java demo のリソース名は GET /api/hello で、ルールの resource がこれと一字一句一致しないかぎり当たりません。

```json
[
  {
    "resource": "GET /api/hello",
    "grade": 1,
    "count": 3,
    "strategy": 0,
    "controlBehavior": 0,
    "limitApp": "default"
  }
]
```

| フィールド      | 指定する値           | 意味                                                                |
| :-------------- | :------------------- | :------------------------------------------------------------------ |
| resource        | 計測点と一字一句一致 | 保護対象のリソース                                                  |
| grade           | 1                    | しきい値の種類。1 は QPS、0 は同時実行数で現在の profile では未対応 |
| count           | 正の整数             | しきい値。QPS の場合は時間窓内のリクエスト数                        |
| strategy        | 0                    | 照合戦略。0 は現在のリソースに直接照合                              |
| controlBehavior | 0                    | 制御動作。0 は即時拒否                                              |
| limitApp        | default              | 呼び出し元。default は呼び出し元を区別しません                      |

> **注記** これらのフィールドは「推奨値」ではなく硬い制約です。Java アダプタは検証段階でスナップショット全体を拒否します。clusterMode、warmUpPeriodSec、maxQueueingTimeMs のいずれかを 1 つでも書くと、ルール全体が無視されるのではなく拒否されます。

## Reporter を接続する

上報が有効になるのは METRICS_COLLECTOR_URL を設定した場合だけです。Java は PKCS#12 形式のクライアント識別子を使い、Go と Rust との最大の違いはここです。

1. 先に Console 側で証明書フィンガープリントを登録します。sentinel-console metrics-reporter enroll に principal、証明書の SHA-256 フィンガープリント、reporter-id、environment-id、app-id、instance-id、process-id を付けます。
2. 秘密鍵は決して Console や Collector に渡しません。
3. bearer token や独自の識別ヘッダで mTLS を置き換える方法は受け付けられません。
4. 読込観測を有効にするには、RULE_BINDING_ID と RULE_PROFILE_ID=sentinel-java-v1 も必要です。

| 変数                           | 説明                                                                |
| :----------------------------- | :------------------------------------------------------------------ |
| METRICS_COLLECTOR_URL          | Collector の HTTPS アドレス。https 以外だと起動時にエラーになります |
| METRICS_REPORTER_ID            | Console に登録済みの Reporter 識別子                                |
| METRICS_CLIENT_PKCS12          | PKCS#12 クライアント識別子ファイルのパス                            |
| METRICS_CLIENT_PKCS12_PASSWORD | PKCS#12 のパスワード。secret manager から供給します                 |
| METRICS_COLLECTOR_CA           | Collector サーバを検証する CA バンドル                              |

> **注記** demo の上報キューは有限でメモリ上にあり、プロセスがクラッシュすると未送达の受信確認を失う可能性があります。本番向け SDK の信頼性保証ではありません。

## 3 ステップの検証

検証は 3 層に分かれます。ルールの読込、インスタンスの読込、リクエストの拒否です。各層に明確な観測点があります。

1. ルールの読込：/rules をリクエストし、出力に rules_loaded=true と rule_count があることを確認します。このステップは内容が読めることしか証明しません。
2. 読込の確認：1 つのポーリング周期を待ってから、ルールページのインスタンス利用状況に、そのインスタンスが読み込んだと表示されることを確認します。このステップはプロセスがスナップショットを受け取ったことを証明します。
3. 遮断の確認：/api/hello を連続でリクエストします。最初の数回は 200 hello from Java Sentinel を返し、しきい値を超えると 429 blocked by Sentinel を返します。
4. 指標の確認：概要とリアルタイム監視に HTTP QPS とリクエスト拒否率が現れます。

> **注記** ルールは 1 秒ごとにポーリングされます。設定センターの内容を変更したら最大 1 秒待ってから確認してください。すぐに読み取ると古い値を読むことがよくあります。

## よくある失敗箇所

次の表は「現象 → 原因 → 対処」の形で、Java demo でよく起こる問題をまとめます。demo は相互運用デモで、失敗モードは本番アダプタより限定的です。設定項目を誤ると起動段階で直接終了し、縮退動作にはなりません。

| 現象                                                                      | 原因                                                                                                                                                                                | 対処                                                                                                                                                 |
| :------------------------------------------------------------------------ | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------- |
| 起動直後に終了し、NACOS_PASSWORD is required と表示される                 | NACOS_AUTH_ENABLED の既定値は true で、認証有効時は NACOS_PASSWORD に既定値がない                                                                                                   | secret manager または shell から NACOS_PASSWORD を注入します。ローカルで認証なしの環境では NACOS_AUTH_ENABLED=false を明示します                     |
| 起動直後に終了し、unsupported RULE_SOURCE_PROVIDER と表示される           | RULE_SOURCE_PROVIDER は nacos または consul のみ受け付け、大文字小文字や別名の正規化は行わない                                                                                      | 正確な小文字の nacos または consul と書きます。Consul に切り替える場合は CONSUL_URL と CONSUL_KEY も指定します                                       |
| ルールが読めない。起動時に終了するか、/rules が rules_loaded=false になる | NACOS_SERVER_ADDR は host:port を 1 つにまとめる必要があり、127.0.0.1 だけだと接続できません。NACOS_NAMESPACE、NACOS_GROUP、NACOS_DATA_ID のいずれかが一致しない場合も空を読みます  | ポート付きの形式にし、namespace・group・Data ID を 1 つずつ照合します                                                                                |
| ルールは読み込まれたのにリクエストが常に通り、リクエスト拒否率が 0 のまま | ルールの resource が計測点と一致していません。Java demo の計測点は GET /api/hello で固定です                                                                                        | resource を計測点と一字一句一致する文字列にします。パス接頭辞もクエリ文字列も含めません                                                              |
| 読込状態が不明、またはローカルと食い違う                                  | RULE_PROFILE_ID はコンソールのバインディングの profile と一致する必要があり、Java は sentinel-java-v1 です。マネージドエンベロープでは RULE_BINDING_ID も合致している必要があります | バインディングの profile、RULE_PROFILE_ID、RULE_BINDING_ID を揃えます。managed-envelope-v1 を使う場合はエンベロープ内の profile が同じ値か確認します |
| コンソールに指標が一切表示されない                                        | METRICS_COLLECTOR_URL を設定していないと上報そのものが有効にならず、アドレスが https でなくても拒否されます                                                                         | METRICS_COLLECTOR_URL を https で設定します。METRICS_REPORTER_ID は Console に登録済みの識別子である必要があります                                   |
| 上報時に証明書関連のエラーが出る                                          | Java は PKCS#12 を使います。METRICS_CLIENT_PKCS12 が指すファイルが存在しないか、METRICS_CLIENT_PKCS12_PASSWORD が誤っています                                                       | PKCS#12 のパスとパスワードを確認します。Go と Rust の PEM 用変数名は Java では無効で、2 組の変数名は共通ではありません                               |

> **注記** この表は demo 自身の設定問題だけを扱います。ルール自体が拒否されたとか、指標の定義が合わないとかの判断は、それぞれ「ルールを 1 件書く」と指標の定義の節を参照してください。

## 公式ドキュメント

- [Sentinel Java](https://sentinelguard.io/en-us/docs/introduction.html)
