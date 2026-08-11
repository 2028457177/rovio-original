"""SubAgentRegistry 注册中心测试。

SubAgent dataclass 可独立创建（不触发 build_agent / LLM），
注册中心的 register/get/all/by_category/find_by_tool/get_all_tools/descriptions_for_planner
均为纯字典操作，不依赖 LLM。
"""
import pytest

from AIRAGAgent.agent.sub_agent import SubAgent, SubAgentRegistry


@pytest.fixture(autouse=True)
def fresh_registry():
    """每个测试用独立 registry（SubAgentRegistry 是单例，需重置）。"""
    reg = SubAgentRegistry()
    reg._agents = {}
    reg._initialized = True
    yield reg
    reg._agents = {}


def _make_tool(name):
    """创建带 .name 属性的 mock 工具。"""
    class _T:
        def __init__(self, n):
            self.name = n
    return _T(name)


# ═══════════════════════════════════════════════
# 注册 + 查询
# ═══════════════════════════════════════════════

def test_register_and_get(fresh_registry):
    agent = SubAgent(name="weather", description="天气查询", tools=[_make_tool("get_weather")])
    fresh_registry.register(agent)
    assert fresh_registry.get("weather") is agent


def test_get_nonexistent(fresh_registry):
    assert fresh_registry.get("no_such") is None


def test_register_overwrites(fresh_registry):
    """同名 SubAgent 注册第二次覆盖第一次"""
    a1 = SubAgent(name="x", description="v1")
    a2 = SubAgent(name="x", description="v2")
    fresh_registry.register(a1)
    fresh_registry.register(a2)
    assert fresh_registry.get("x").description == "v2"


def test_all_returns_copy(fresh_registry):
    """all() 返回副本，外部修改不影响内部"""
    fresh_registry.register(SubAgent(name="a", description="x"))
    all_agents = fresh_registry.all()
    all_agents["injected"] = SubAgent(name="injected", description="")
    assert "injected" not in fresh_registry.all()


def test_all_empty(fresh_registry):
    assert fresh_registry.all() == {}


# ═══════════════════════════════════════════════
# by_category
# ═══════════════════════════════════════════════

def test_by_category(fresh_registry):
    fresh_registry.register(SubAgent(name="search", description="搜索", category="builtin"))
    fresh_registry.register(SubAgent(name="codexec", description="代码", category="builtin"))
    fresh_registry.register(SubAgent(name="weather", description="天气", category="domain"))

    builtin = fresh_registry.by_category("builtin")
    assert set(builtin.keys()) == {"search", "codexec"}
    domain = fresh_registry.by_category("domain")
    assert set(domain.keys()) == {"weather"}


def test_by_category_empty(fresh_registry):
    assert fresh_registry.by_category("nonexistent") == {}


def test_by_category_default_is_domain(fresh_registry):
    """SubAgent 默认 category=domain"""
    fresh_registry.register(SubAgent(name="x", description=""))
    assert "x" in fresh_registry.by_category("domain")


# ═══════════════════════════════════════════════
# find_by_tool
# ═══════════════════════════════════════════════

def test_find_by_tool(fresh_registry):
    t1 = _make_tool("search_web")
    t2 = _make_tool("fetch_url")
    fresh_registry.register(SubAgent(name="search", description="", tools=[t1, t2]))
    fresh_registry.register(SubAgent(name="codexec", description="", tools=[_make_tool("run_python")]))

    found = fresh_registry.find_by_tool("search_web")
    assert found is not None
    assert found.name == "search"

    found = fresh_registry.find_by_tool("run_python")
    assert found.name == "codexec"


def test_find_by_tool_not_found(fresh_registry):
    fresh_registry.register(SubAgent(name="x", description="", tools=[_make_tool("a")]))
    assert fresh_registry.find_by_tool("nonexistent") is None


def test_find_by_tool_multiple_agents_same_tool_name(fresh_registry):
    """两个 SubAgent 有同名工具时，返回先注册的"""
    fresh_registry.register(SubAgent(name="first", description="", tools=[_make_tool("shared")]))
    fresh_registry.register(SubAgent(name="second", description="", tools=[_make_tool("shared")]))
    found = fresh_registry.find_by_tool("shared")
    assert found.name == "first"


# ═══════════════════════════════════════════════
# get_all_tools
# ═══════════════════════════════════════════════

def test_get_all_tools(fresh_registry):
    fresh_registry.register(SubAgent(name="a", description="", tools=[_make_tool("t1"), _make_tool("t2")]))
    fresh_registry.register(SubAgent(name="b", description="", tools=[_make_tool("t3")]))
    tools = fresh_registry.get_all_tools()
    names = {getattr(t, "name", None) for t in tools}
    assert names == {"t1", "t2", "t3"}


def test_get_all_tools_dedup(fresh_registry):
    """跨 SubAgent 同名工具去重"""
    fresh_registry.register(SubAgent(name="a", description="", tools=[_make_tool("shared")]))
    fresh_registry.register(SubAgent(name="b", description="", tools=[_make_tool("shared")]))
    tools = fresh_registry.get_all_tools()
    assert len(tools) == 1


def test_get_all_tools_empty(fresh_registry):
    assert fresh_registry.get_all_tools() == []


# ═══════════════════════════════════════════════
# descriptions_for_planner
# ═══════════════════════════════════════════════

def test_descriptions_for_planner(fresh_registry):
    fresh_registry.register(SubAgent(
        name="weather", description="查天气",
        workflow_hint="get_location → get_weather",
    ))
    fresh_registry.register(SubAgent(
        name="codexec", description="执行代码",
        workflow_hint="",
    ))
    desc = fresh_registry.descriptions_for_planner()
    assert "weather" in desc
    assert "查天气" in desc
    assert "get_location → get_weather" in desc
    assert "codexec" in desc
    assert "执行代码" in desc


def test_descriptions_for_planner_empty(fresh_registry):
    desc = fresh_registry.descriptions_for_planner()
    assert "可用 SubAgent" in desc
    # 空注册表只有标题行
    assert desc.strip().count("\n") == 0


def test_descriptions_for_planner_no_workflow_hint(fresh_registry):
    """workflow_hint 为空时不输出调用流程行"""
    fresh_registry.register(SubAgent(name="x", description="测试", workflow_hint=""))
    desc = fresh_registry.descriptions_for_planner()
    assert "调用流程" not in desc


def test_descriptions_for_planner_exclude(fresh_registry):
    """联网搜索关闭时排除 search：菜单不出现 search，其余 subagent 不受影响"""
    fresh_registry.register(SubAgent(name="search", description="联网搜索"))
    fresh_registry.register(SubAgent(name="codexec", description="执行代码"))
    desc = fresh_registry.descriptions_for_planner(exclude={"search"})
    assert "search" not in desc
    assert "联网搜索" not in desc
    assert "codexec" in desc
    # 不传 exclude 时不受影响
    assert "search" in fresh_registry.descriptions_for_planner()


# ═══════════════════════════════════════════════
# SubAgent dataclass
# ═══════════════════════════════════════════════

def test_sub_agent_defaults():
    a = SubAgent(name="test", description="desc")
    assert a.tools == []
    assert a.system_prompt == ""
    assert a.workflow_hint == ""
    assert a.max_tool_calls == 20
    assert a.category == "domain"


def test_sub_agent_hash_by_name():
    """SubAgent 按 name 哈希（可放入 set/dict）"""
    a1 = SubAgent(name="x", description="v1")
    a2 = SubAgent(name="x", description="v2")
    # __hash__ 按 name 计算，两个同名 agent 哈希相同
    assert hash(a1) == hash(a2)
    # 但 dataclass __eq__ 比较所有字段，description 不同则不等
    assert a1 != a2
    # 完全相同的 agent 才会被 set 去重
    a3 = SubAgent(name="x", description="v1")
    s = {a1, a3}
    assert len(s) == 1


def test_sub_agent_custom_fields():
    a = SubAgent(
        name="custom", description="自定义",
        tools=[_make_tool("t1")],
        system_prompt="你是专家",
        workflow_hint="step1 → step2",
        max_tool_calls=10,
        category="builtin",
    )
    assert a.max_tool_calls == 10
    assert a.category == "builtin"
    assert len(a.tools) == 1


# ═══════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════

def test_registry_is_singleton():
    """SubAgentRegistry 是单例"""
    a = SubAgentRegistry()
    b = SubAgentRegistry()
    assert a is b
