# terra-py-form 仕様書

## 1. 概要

- **プロジェクト名**: terra-py-form
- **タイプ**: AWS向けInfrastructure as Codeフレームワーク
- **コア機能**: YAMLで定義されたAWSリソースをグラフ化し、依存関係を解決してdry-run表示する
- **ターゲットユーザー**: AWSエンジニア、DevOpsエンジニア

## 2. 技術スタック

- **言語**: Python 3.10+
- **依存**: boto3（AWS API呼び出し用）のみ原則
- **設定ファイル**: YAML（インフラ定義）
- **ステート管理**: JSONファイル（デフォルト: `./state.json`）

## 3. 用語・概念

| 用語 | 定義 |
|------|------|
| **リソース (Resource)** | AWSリソース定義の最小単位（例: S3 Bucket, EC2 Instance） |
| **グラフ (Graph)** | リソース間の依存関係を表現する有向非巡回グラフ（DAG） |
| **ノード (Node)** | グラフの頂点＝リソース |
| **エッジ (Edge)** | グラフの辺＝依存関係 |
| **oplan (Output Plan)** | 適用計画の表示（Terraformのtfplan相当） |
| **ステート (State)** | 現在のリソース管理 состояние |

## 4. YAML定義フォーマット

```yaml
version: "1.0"

resources:
  # 明示的依存（depends_on)
  vpc:
    type: aws_vpc
    properties:
      cidr_block: "10.0.0.0/16"
    depends_on: []

  subnet_a:
    type: aws_subnet
    properties:
      vpc_id: ${vpc.id}  # 暗黙的依存（参照解決）
      cidr_block: "10.0.1.0/24"
      availability_zone: "ap-northeast-1a"
    depends_on:
      - vpc

  # 明示的依存
  security_group:
    type: aws_security_group
    properties:
      vpc_id: ${vpc.id}
      ingress:
        - from_port: 443
          to_port: 443
          protocol: "tcp"
    depends_on:
      - vpc

  instance:
    type: aws_instance
    properties:
      ami: "ami-0c55b159cbfafe1f0"
      instance_type: "t3.micro"
      subnet_id: ${subnet_a.id}
    depends_on:
      - subnet_a
      - security_group
```

### 参照構文

- `${resource_name.property}` 形式で他のリソースのプロパティを参照
- 循環参照はエラー

## 5. コア機能

### 5.1 グラフ構築

1. YAMLからリソースリストをパース
2. 各リソースの `depends_on` から明示的依存エッジを追加
3. プロパティ内の `${}` 参照から暗黙的依存エッジを追加
4. グラフの簡約化（推移的依存の圧縮）

### 5.2 ループ検知

- **アルゴリズム**: DFS + visited set
- **検出時**: `CircularDependencyError` を発生させ、関与するリソース名を報告
- **処理**: 検出したら即座にエラーで停止

### 5.3 依存解決（ топソロジカルソート）

- **アルゴリズム**: Kahnのアルゴリズム
- **出力**: リソースの適用順序リスト

### 5.4 Dry-Run（oplan表示）

- 各リソースについて、作成/変更/削除 plan を表示
- 差分内容をテキストテーブル形式で出力

### 5.5 ステート管理

- `state.json` ファイルで管理
- 構造:
```json
{
  "version": "1.0",
  "resources": {
    "vpc": {
      "type": "aws_vpc",
      "properties": {...},
      "id": "vpc-12345"
    }
  },
  "updated_at": "2024-01-01T00:00:00Z"
}
```

## 6. CLIコマンド

```bash
# oplan表示（dry-run）
python -m terra_py_form plan <yaml_file>

# 適用
python -m terra_py_form apply <yaml_file>

# ステート確認
python -m terra_py_form state show

# ステート削除
python -m terra_py_form state rm <resource_name>
```

## 7. ディレクトリ構成

```
terra-py-form/
├── terra_py_form/
│   ├── __init__.py
│   ├── cli.py          # CLIエントリポイント
│   ├── parser.py      # YAMLパース
│   ├── graph.py       # グラフ構築・簡約
│   ├── solver.py      # 依存解決・ループ検知
│   ├── planner.py     # oplan生成
│   ├── executor.py    # boto3 apply
│   └── state.py       # ステート管理
├── tests/
├── docs/
├── examples/
├── pyproject.toml
└── README.md
```

## 8. テスト戦略

### Phase 1: グラフ構築
- YAMLパース精度
- 明示的依存エッジ生成
- 暗黙的依存エッジ生成（${}参照解決）
- グラフ簡約

### Phase 2: ループ検知
- 正常グラフ（ループなし）の許容
- 単一ループの検出
- 複数ループの検出

### Phase 3: 依存解決
- 単純な依存チェーン
- 並列可能リソースの識別
- 複雑な依存グラフ

### Phase 4: Dry-Run
- boto3 mock による計画作成
- 差分検出精度

### Phase 5: E2E
- 実際のAWS環境での動作確認（dry-runのみ）

## 9. 制約・制約事項

- 対応AWSリソースは初期版では主要リソース（S3, VPC, EC2, SecurityGroup, Subnet）のみ
- 認証・認可は ~/.aws/credentials または環境変数から自動取得（boto3デフォルト）
- Windows非対応（Linux/macOSのみサポート）
