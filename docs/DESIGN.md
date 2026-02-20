# terra-py-form 設計書

## 1. 全体アーキテクチャ：Hot/Cold分離

```
┌─────────────────────────────────────────────────────────────────┐
│                           CLI                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     cold: コアエンジン                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │  Parser  │─▶│  Graph   │─▶│  Solver  │─▶│    Planner    │   │
│  │  (YAML)  │  │ (DAG)    │  │(排序/loop)│  │  (差分計算)   │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────┘   │
│         │                                    │                 │
│         ▼                                    ▼                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │                     StateManager                          │ │
│  │                   (状態永続化)                             │ │
│  └──────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   hot: プロバイダアダプタ                        │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐               │
│  │ EC2Adapter │  │ RDSAdapter │  │ ...Adapter │               │
│  │            │  │            │  │            │               │
│  │ +diff()    │  │ +diff()    │  │ +diff()    │  ← 差分生成    │
│  │ +create()  │  │ +create()  │  │ +create()  │  ← 実API       │
│  │ +update()  │  │ +update()  │  │ +update()  │               │
│  │ +delete()  │  │ +delete()  │  │ +delete()  │               │
│  │ +describe()│  │ +describe()│  │ +describe()│               │
│  └────────────┘  └────────────┘  └────────────┘               │
└─────────────────────────────────────────────────────────────────┘
```

### Hot/Cold 分離の原則

| レイヤー | 種類 | 変更頻度 | テスト戦略 |
|---------|------|---------|-----------|
| Parser/Graph/Solver/Planner | Cold | 低 | Mocks不要、純粋関数テスト |
| StateManager | Cold | 低 | File I/Oテスト |
| *Adapter (EC2/RDS/...) | Hot | 高 | AWS SDK Mock必須 |

---

## 2. Cold: コアエンジン設計

### 2.1 parser.py - YAMLパース

```python
# cold/parser.py
from dataclasses import dataclass, field
from typing import Any
import yaml

@dataclass
class Resource:
    """インフラリソースの中間表現"""
    name: str              # YAMLキー: "my_vpc"
    type: str              # "aws:ec2:vpc"
    properties: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)  # ${ref(xxx)}

@dataclass
class InfraDefinition:
    """YAML全体のパース結果"""
    version: str
    variables: dict
    resources: list[Resource]

class Parser:
    def parse(self, yaml_path: str) -> InfraDefinition:
        """YAML → InfraDefinition"""
        
    def _extract_refs(self, value: Any) -> list[str]:
        """${ref(xxx.yyy)} 形式の参照を抽出"""
```

### 2.2 graph.py - 依存グラフ構築

```python
# cold/graph.py
from dataclasses import dataclass, field
from typing import Set
from .parser import Resource, InfraDefinition

@dataclass
class Node:
    """グラフノード"""
    resource: Resource
    outgoing: Set[str] = field(default_factory=set)  # 自分 → 依存先
    incoming: Set[str] = field(default_factory=set)  # 依存元 → 自分

class Graph:
    """依存グラフ（DAG）"""
    nodes: dict[str, Node]
    
    def __init__(self, definition: InfraDefinition):
        self.nodes = {}
        self._build(definition)
    
    def _build(self, definition: InfraDefinition):
        """明示的depends_on + 暗黙的${ref()}からエッジ生成"""
        for res in definition.resources:
            # 1. 明示的依存
            for dep in res.depends_on:
                self._add_edge(res.name, dep)
            
            # 2. 暗黙的依存 (${ref(xxx)})
            for ref in res.source_refs:
                self._add_edge(res.name, ref)
    
    def simplify(self):
        """推移的依存を削除してグラフを簡約化"""
```

### 2.3 solver.py - 依存解決

```python
# cold/solver.py
from typing import Optional
from .graph import Graph

class CycleError(Exception):
    """循環依存エラー"""
    def __init__(self, path: list[str]):
        self.path = path
        super().__init__(f"Circular dependency: {' → '.join(path)}")

class Solver:
    """依存解決（ループ検知 + ソート）"""
    
    def detect_cycle(self, graph: Graph) -> Optional[list[str]]:
        """DFSでループ検知。ループ経路を返す"""
        
    def topological_sort(self, graph: Graph) -> list[str]:
        """Kahnのアルゴリズムでリソース適用順序を返す"""
        # 循環 있으면 CycleError
```

### 2.4 planner.py - 差分計画

```python
# cold/planner.py
from dataclasses import dataclass
from typing import Literal
from .graph import Graph
from .state import State

Action = Literal["create", "update", "delete", "noop"]

@dataclass
class Diff:
    """リソース差分"""
    resource_name: str
    resource_type: str
    action: Action
    before: dict | None  # 旧state
    after: dict | None   # 新定義
    changes: dict        # {field: (old, new)}

class Planner:
    """新旧stateの差分を計算"""
    
    def __init__(self, state: State):
        self.state = state
    
    def plan(self, definition: Graph, dry_run: bool = True) -> list[Diff]:
        """全リソースのDiffリスト生成"""
        #  cold: 差分ロジックはAWS非依存
        #  actual diff generation は hot Adapter にdelegation
```

### 2.5 state.py - 状態管理

```python
# cold/state.py
from dataclasses import dataclass, field, asdict
from datetime import datetime
import json
from pathlib import Path

@dataclass
class ResourceState:
    """单项リソースの状態"""
    resource_type: str
    identifier: dict      # {arn: "...", id: "..."}
    properties: dict
    updated_at: str

@dataclass
class State:
    """TF状態ファイル"""
    version: str = "1.0"
    resources: dict[str, ResourceState] = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def save(self, path: str | Path):
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
    
    @classmethod
    def load(cls, path: str | Path) -> "State":
        with open(path) as f:
            data = json.load(f)
        # dataclass再構築
```

---

## 3. Hot: プロバイダアダプタ設計

### 3.1 アダプタ基底クラス

```python
# hot/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
import boto3

@dataclass
class ResourceDiff:
    """Adapter-specific 差分生成用"""
    field_path: str
    old_value: Any
    new_value: Any

class BaseAdapter(ABC):
    """プロパイドアダプタの基底クラス"""
    
    # サブクラスで定義
    RESOURCE_TYPE: str  # e.g., "aws:ec2:vpc"
    
    def __init__(self, session: boto3.Session | None = None):
        self.session = session or boto3.Session()
        self.client = self._client()
    
    @abstractmethod
    def _client(self):
        """boto3 client 生成"""
        pass
    
    @abstractmethod
    def describe(self, identifier: dict) -> dict | None:
        """現在state取得。存在しないならNone"""
        pass
    
    @abstractmethod
    def diff(self, desired: dict, actual: dict | None) -> list[ResourceDiff]:
        """新旧差分生成"""
        pass
    
    @abstractmethod
    def create(self, properties: dict) -> dict:
        """リソース作成。成功后のidentifierを返す"""
        pass
    
    @abstractmethod
    def update(self, identifier: dict, changes: list[ResourceDiff]) -> dict:
        """リソース更新"""
        pass
    
    @abstractmethod
    def delete(self, identifier: dict):
        """リソース削除"""
        pass
    
    # 共通ユーティリティ
    def _filter_sensitive(self, props: dict) -> dict:
        """Password等を除外したプロパティ 반환"""
```

### 3.2 EC2 アダプタ

```python
# hot/adapters/ec2.py
import boto3
from ..base import BaseAdapter, ResourceDiff

class VPCAdapter(BaseAdapter):
    RESOURCE_TYPE = "aws:ec2:vpc"
    
    def _client(self):
        return self.session.client("ec2")
    
    def describe(self, identifier: dict) -> dict | None:
        try:
            resp = self.client.describe_vpcs(VpcIds=[identifier["vpc_id"]])
            return resp["Vpcs"][0] if resp["Vpcs"] else None
        except self.client.exceptions.VpcNotFound:
            return None
    
    def diff(self, desired: dict, actual: dict | None) -> list[ResourceDiff]:
        if not actual:
            return []  # 全プロパティがcreate対象
        
        diffs = []
        for key, desired_val in desired.items():
            actual_val = actual.get(key)
            if desired_val != actual_val:
                diffs.append(ResourceDiff(key, actual_val, desired_val))
        return diffs
    
    def create(self, properties: dict) -> dict:
        resp = self.client.create_vpc(
            CidrBlock=properties["cidr_block"],
            TagSpecifications=[{"ResourceType": "vpc", "Tags": properties.get("tags", [])}]
        )
        return {"vpc_id": resp["Vpc"]["VpcId"], "arn": resp["Vpc"]["VpcArn"]}
    
    def update(self, identifier: dict, changes: list[ResourceDiff]) -> dict:
        # VPC更新ロジック
        pass
    
    def delete(self, identifier: dict):
        self.client.delete_vpc(VpcId=identifier["vpc_id"])


class SubnetAdapter(BaseAdapter):
    """Subnet 用 Adapter - VPC への暗黙依存あり"""
    RESOURCE_TYPE = "aws:ec2:subnet"
    
    # $ref(vpc.id) を解決するために client が必要
    # cold からは type だけ見えて、client は実行時に注入
```

### 3.3 RDS アダプタ

```python
# hot/adapters/rds.py
import boto3
from ..base import BaseAdapter, ResourceDiff

class DBInstanceAdapter(BaseAdapter):
    RESOURCE_TYPE = "aws:rds:db_instance"
    
    def _client(self):
        return self.session.client("rds")
    
    def describe(self, identifier: dict) -> dict | None:
        try:
            resp = self.client.describe_db_instances(
                DBInstanceIdentifier=identifier["db_instance_id"]
            )
            return resp["DBInstances"][0] if resp["DBInstances"] else None
        except self.client.exceptions.DBInstanceNotFound:
            return None
    
    def diff(self, desired: dict, actual: dict | None) -> list[ResourceDiff]:
        # RDS特有: 某些参数不支持更新，需要recreate判断
        pass
    
    def create(self, properties: dict) -> dict:
        # MasterUserPassword は secretsmanager から取得等专业处理
        pass
```

### 3.4 アダプタレジストリ

```python
# hot/registry.py
from .base import BaseAdapter

class AdapterRegistry:
    """プロパイダ登録・解決"""
    
    _adapters: dict[str, type[BaseAdapter]] = {}
    
    @classmethod
    def register(cls, resource_type: str, adapter_class: type[BaseAdapter]):
        cls._adapters[resource_type] = adapter_class
    
    @classmethod
    def get(cls, resource_type: str) -> BaseAdapter:
        if resource_type not in cls._adapters:
            raise NotImplementedError(f"Adapter for {resource_type} not found")
        return cls._adapters[resource_type]()

# 登録
from .adapters.ec2 import VPCAdapter, SubnetAdapter
from .adapters.rds import DBInstanceAdapter

AdapterRegistry.register("aws:ec2:vpc", VPCAdapter)
AdapterRegistry.register("aws:ec2:subnet", SubnetAdapter)
AdapterRegistry.register("aws:rds:db_instance", DBInstanceAdapter)
```

---

## 4. テスト戦略

### 4.1 Cold テスト（SDK Mock不要）

```
tests/cold/
├── test_parser.py       # YAML → Resource[]
├── test_graph.py        # DAG構築、推移簡約
├── test_solver.py       # ループ検知、topo sort
├── test_planner.py      # Diff生成ロジック
└── test_state.py        # save/load
```

```python
# test_graph.py 例
def test_explicit_dependency():
    definition = InfraDefinition(
        version="1.0",
        variables={},
        resources=[
            Resource("vpc", "aws:ec2:vpc", {}, [], []),
            Resource("subnet", "aws:ec2:subnet", {}, ["vpc"], [])
        ]
    )
    graph = Graph(definition)
    assert "vpc" in graph.nodes["subnet"].outgoing
```

### 4.2 Hot テスト（SDK Mock必須）

```
tests/hot/
├── test_ec2_adapter.py    # moto利用
├── test_rds_adapter.py
└── test_registry.py
```

```python
# test_ec2_adapter.py 例
import moto

@moto.mock_aws
def test_vpc_create():
    adapter = VPCAdapter()
    result = adapter.create({"cidr_block": "10.0.0.0/16"})
    assert result["vpc_id"].startswith("vpc-")
```

### 4.3 統合テスト

```
tests/integration/
├── test_plan_flow.py      # Parser → Graph → Solver → Planner 全体
└── test_apply_flow.py     # 実適用（含AWS API）
```

---

## 5. ディレクトリ構成

```
terra-py-form/
├── pyproject.toml
├── src/
│   └── terra_py_form/
│       ├── __init__.py
│       ├── cli.py                 # CLIエントリポイント
│       ├── cold/                  # 汎用エンジン
│       │   ├── __init__.py
│       │   ├── parser.py
│       │   ├── graph.py
│       │   ├── solver.py
│       │   ├── planner.py
│       │   └── state.py
│       └── hot/                   # AWS固有
│           ├── __init__.py
│           ├── base.py
│           ├── registry.py
│           └── adapters/
│               ├── __init__.py
│               ├── ec2.py
│               └── rds.py
├── tests/
│   ├── cold/
│   ├── hot/
│   └── integration/
└── docs/
    ├── SPEC.md
    └── DESIGN.md
```

---

## 6. 拡張パターン（新サービス追加）

### Step 1: Adapter実装
```python
# hot/adapters/s3.py
class S3BucketAdapter(BaseAdapter):
    RESOURCE_TYPE = "aws:s3:bucket"
    # 実装...
```

### 2行で登録
```python
AdapterRegistry.register("aws:s3:bucket", S3BucketAdapter)
```

### テスト追加
```python
# tests/hot/test_s3_adapter.py
# motoでS3Mock化してテスト
```

→ **coldコード一切触らずにサービス追加完了**

---

## 7. 参照実装

- Terraform Provider実装モデル
- Pythonのbotocore/stubber
- moto: AWS Mockライブラリ
