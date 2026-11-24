"""仪表盘业务投影及真实浏览器筛选函数的专属回归。"""
import json
import shutil
import subprocess
import unittest
from dashboard_projection import project_task
from dashboard_page import page_html


class PresentationTests(unittest.TestCase):
    def task(self, **updates):
        current = dict(id="r", state="implementing", phase="implementation", todos=[], attempts=[], evidence=[])
        current.update(updates)
        return project_task(dict(id="T1", protocol_version=2, current_round="r", baseline=["docs/a.md"], missing=["checks", "review", "baseline"], rounds=[current]), {})

    def test_phase_aware_missing_and_unknown(self):
        item = self.task()
        self.assertEqual(item["readiness"]["blocking"], ["基线尚未完成有效读取"])
        self.assertEqual(item["readiness"]["upcoming"], ["后续验证尚未完成", "后续双轴评审尚未完成"])
        self.assertNotIn("通过", self.task(state="nonsense")["summary"])

    def test_invalid_baseline_and_verification_only(self):
        item = self.task(evidence=[dict(kind="baseline", valid=False, data=dict(path="docs/a.md", complete=True))], attempts=[dict(stage="implementation", status="failed"), dict(stage="verification", status="error", failure="RUN_ERROR", results=[dict(id="lint", exit_code=2, reason="exit", stderr="bad")])])
        self.assertEqual(item["business"]["baseline"][0]["status"], "已失效")
        self.assertEqual(len(item["business"]["verification"]), 1)
        self.assertEqual(len(item["failures"]), 1)
        self.assertEqual(item["business"]["verification"][0]["checks"][0]["stderr"], "bad")

    def test_unread_and_deduplicated_invalidation(self):
        self.assertEqual(self.task()["business"]["baseline"][0]["status"], "未读")
        item = self.task(evidence=[dict(kind="review", valid=False, reason="changed"), dict(kind="review", valid=False, reason="changed")])
        self.assertEqual(len(item["business"]["invalidations"]), 1)

    def test_current_blockers_and_dual_review_are_not_pass_by_default(self):
        item = self.task(phase="review", missing=["checks", "review", "future_flag"], evidence=[dict(kind="review", valid=True, data=dict(axes=dict(spec=dict(conclusion="pass", findings=[]), standards=dict(conclusion="fail", findings=[dict(message="补充边界测试", required=True, resolved=False)]))))], required_findings=dict(standards={"f": False}))
        self.assertEqual(item["readiness"]["upcoming"], [])
        self.assertEqual(len(item["readiness"]["blocking"]), 3)
        self.assertEqual(item["business"]["review"][1]["unresolved"], 1)
        self.assertEqual(item["business"]["review"][1]["conclusion"], "fail")
        self.assertEqual(self.task()["business"]["review"][0]["conclusion"], "unknown")

    def test_pass_axis_with_unresolved_required_findings_is_not_pass(self):
        item = self.task(evidence=[dict(kind="review", data=dict(axes=dict(spec=dict(conclusion="pass", findings=[]))))], required_findings=dict(spec={"unresolved": False}))
        self.assertEqual(item["business"]["review"][0]["conclusion"], "fail")

    def test_baseline_binding_and_control_changes_invalidate(self):
        for change in ({"session_id": "new"}, {"control_digest": "new"}):
            item = self.task(**change, evidence=[dict(kind="baseline", valid=True, control_digest="old", data=dict(path="docs/a.md", complete=True, session_id="old"))])
            self.assertEqual(item["business"]["baseline"][0]["status"], "已失效")

    def test_page_security_and_collapsed_technical_details(self):
        page = page_html()
        self.assertNotIn("innerHTML", page)
        self.assertNotIn("setInterval", page)
        self.assertIn("if (polling) return", page)
        self.assertIn("技术详情 · 原始记录", page)
        self.assertNotIn("<details open", page)
        self.assertIn("raw.slice(0,16384)", page)
        self.assertIn("@media(max-width:600px)", page)
        self.assertIn('<details id="document-sources"', page)

    @unittest.skipUnless(shutil.which("node"), "Node 不可用")
    def test_real_render_prioritizes_attention_and_preserves_details(self):
        task = dict(id="T2", protocol_version=2, current_round="r", goal="目标业务", scope="范围业务", acceptance=["验收业务"], proposal=dict(goal="方案业务", risk="风险业务", rollback="回滚业务"), plan=dict(checks=[dict(id="lint", argv=["python3", "-m", "unittest"], cwd=".")]), rounds=[dict(id="r", state="implementing", phase="implementation", todos=[dict(title="步骤甲", status="done"), dict(title="步骤乙", status="pending")], handoff=dict(next_step="交接业务"))])
        pending = [dict(question="确认业务", impact="影响业务", owner="负责人业务", resume="恢复业务", source="docs/card.md｜产品业务")]
        item = project_task(task, dict(pending=pending))
        self.assertEqual(item["pending"], pending)
        stub = r'''class Node {
          constructor(tag) { this.tag=tag;this.children=[];this.style={};this.dataset={};this.open=false;this.value='';this.content='';this.events={};this.isConnected=true; }
          set textContent(v) { this.content=String(v);this.children=[]; }
          get textContent() { return this.content+this.children.map(n=>n.textContent).join(' '); }
          append(...nodes) { this.children.push(...nodes); }
          replaceChildren(...nodes) { this.content='';this.children=nodes; }
          addEventListener(name, handler) { this.events[name]=handler; }
          toggle(open) { this.open=open;this.events.toggle?.(); }
        }
        const nodes={}; const document={createElement:tag=>new Node(tag),getElementById:id=>nodes[id]||(nodes[id]=new Node('div'))};
        function visible(n, excludeTechnical=false) { if(excludeTechnical&&n.className==='technical')return '';if(n.tag==='details'&&!n.open)return n.children.filter(c=>c.tag==='summary').map(c=>visible(c,excludeTechnical)).join(' ');return n.content+' '+n.children.map(c=>visible(c,excludeTechnical)).join(' '); }
        function walk(n) { return [n,...n.children.flatMap(walk)]; }
        '''
        script = page_html().split("<script>")[1].split("</script>")[0].split("byId('refresh').addEventListener")[0]
        assertions = r'''
        if(badge('review_passed').dataset.tone!=='good'||badge('passed').dataset.tone!=='good'||badge('failed').dataset.tone!=='bad'||badge('implementing').dataset.tone!=='active')throw Error('徽章色调映射错误');
        nodes['state-filter']=new Node('select');nodes['state-filter'].value='all';nodes['tier-filter']=new Node('select');nodes['tier-filter'].value='all';
        renderTasks([fixture]); const card=nodes.tasks.children[0];
        const initial=visible(card,true);
        if(!initial.includes('确认业务') || !initial.includes('实施 1/2'))throw Error('默认任务摘要缺失');
        for(const word of ['影响业务','负责人业务','恢复业务','步骤甲','步骤乙'])if(initial.includes(word))throw Error('默认展示了详情：'+word);
        const details=walk(card).find(n=>n.className==='task-details');
        details.toggle(true);
        if(!visible(card,true).includes('恢复业务'))throw Error('展开应显示对应的待确认记录');
        renderTasks([fixture]);
        if(!visible(nodes.tasks,true).includes('恢复业务'))throw Error('刷新后应保留已展开的详情');
        const all=walk(card); const technical=all.find(n=>n.className==='technical');
        if(!technical||technical.open)throw Error('技术详情必须关闭');
        for(const d of all.filter(n=>n.className==='business-section'&&n.tag==='details'))d.toggle(true);
        const business=visible(card,true);
        for(const word of ['影响业务','负责人业务','docs/card.md｜产品业务','步骤甲','步骤乙','目标业务','范围业务','验收业务','方案业务','风险业务','回滚业务','python3 -m unittest','人工验收尚未发生','交接业务'])if(!business.includes(word))throw Error('业务详情缺失：'+word);
        if(business.includes('"goal":'))throw Error('业务区不得输出原始JSON');
        const internal=JSON.stringify(technicalRecord(fixture));
        for(const word of ['目标业务','验收业务','确认业务','交接业务'])if(internal.includes(word))throw Error('技术区混入业务字段：'+word);
        if(businessLines({goal:'可读目标',session_id:'私密会话',unknown_field:'原始隐藏'}).join(' ').includes('私密会话'))throw Error('业务字段白名单失败');
        const blocked={...fixture,readiness:{blocking:['缺少基线','未批准']}};
        if(taskHighlight(blocked).label!=='当前阻止' || taskHighlight(blocked).remaining!==2)throw Error('应优先展示阻止条件和其余事项数量');
        const failed={...fixture,state:'failed',readiness:{blocking:['当前验证尚未通过']},business:{verification:[{status:'failed',checks:[{id:'format',exit_code:0,reason:'exit'},{id:'lint',exit_code:2,reason:'exit'}]}]}};
        if(taskHighlight(failed).message!=='lint · 退出码 2')throw Error('验证失败应展示实际失败的检查');
        const current={...fixture,state:'running',business:failed.business,pending:[]};
        if(taskHighlight(current).label==='验证失败')throw Error('历史失败不可当作当前失败');
        renderDocuments([{path:'docs/a.md',exists:true},{path:'docs/b.md',exists:false},{path:'docs/c.md'}]);
        if(nodes['document-count'].textContent!=='3 份 · 1 份缺失 · 1 份状态未知')throw Error('文档来源应汇总已知状态');
        if(nodes.documents.children[0].disabled||!nodes.documents.children[1].disabled)throw Error('预览按钮应该按存在性启用');
        '''
        result = subprocess.run(["node", "-e", stub + script + "\nconst fixture=" + json.dumps(item, ensure_ascii=False) + ";" + assertions], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node 不可用")
    def test_real_filter_combines_query_state_and_tier(self):
        script = page_html().split("<script>")[1].split("</script>")[0]
        script = script.split("byId('refresh').addEventListener")[0]
        cases = [{"id":"T1", "title":"搜索功能", "state":"implementing", "tier":"standard"}, {"id":"T2", "title":"搜索功能", "state":"failed", "tier":"full"}]
        script += "\nconst tasks=" + json.dumps(cases, ensure_ascii=False) + ";\n"
        script += "if(filterTasks(tasks,'搜索','implementing','standard').length!==1)throw Error('组合筛选'); if(filterTasks(tasks,'T2','implementing','all').length!==0)throw Error('交集'); if(filterTasks(tasks,'failed','all','all').length!==0)throw Error('只搜索编号标题'); if(filterTasks(tasks,'','all','all').length!==2)throw Error('清空');"
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_empty_review_not_invalidated_and_git_card_renders_cleanly(self):
        created = project_task(
            dict(
                id="T-CREATED", protocol_version=2, current_round="r",
                rounds=[dict(id="r", state="created", phase="planning", control_digest="abc", todos=[], attempts=[], evidence=[])],
            ),
            {},
        )
        self.assertEqual(created["business"]["review"][0]["conclusion"], "unknown")

        cancelled = self.task(state="cancelled", phase="done")
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertEqual(cancelled["readiness"]["blocking"], [])

        if shutil.which("node"):
            script = page_html().split("<script>")[1].split("</script>")[0].split("byId('refresh').addEventListener")[0]
            stub = r'''class Node {
              constructor(tag) { this.tag=tag;this.children=[];this.style={};this.dataset={};this.open=false;this.value='';this.content='';this.events={};this.isConnected=true; }
              set textContent(v) { this.content=String(v);this.children=[]; }
              get textContent() { return this.content+this.children.map(n=>n.textContent).join(' '); }
              append(...nodes) { this.children.push(...nodes); }
              replaceChildren(...nodes) { this.content='';this.children=nodes; }
              addEventListener(name, handler) { this.events[name]=handler; }
            }
            const nodes={}; const document={createElement:tag=>new Node(tag),getElementById:id=>nodes[id]||(nodes[id]=new Node('div'))};
            '''
            git_card = {"id": "BASE-UI07", "title": "用 easy_refresh 统一列表刷新加载", "state": "review_passed", "source": "docs/product/任务/全局组件.md:3"}
            checks = r'''
            populateStateOptions();
            const optionValues = nodes['state-filter'].children.map(o => o.value);
            if (optionValues.includes('cancelled') || optionValues.includes('superseded')) throw Error('状态筛选不应包含已取消或已结案');
            nodes['state-filter'].value='all';
            nodes['tier-filter']=new Node('select');
            nodes['tier-filter'].value='all';
            renderTasks([gitCard]);
            const rendered = nodes.tasks.children[0].textContent;
            if (!rendered.includes('Git 任务卡') || rendered.includes('档位未知') || rendered.includes('阶段未知')) throw Error('纯 Git 任务卡渲染不符合预期：' + rendered);
            if (taskHighlight(gitCard).label !== 'Git 任务卡') throw Error('纯 Git 任务卡焦点标签错误');
            '''
            payload = f"\nconst gitCard={json.dumps(git_card, ensure_ascii=False)};\n"
            result = subprocess.run(["node", "-e", stub + script + payload + checks], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node 不可用")
    def test_pipeline_spotlight_and_cyber_bot_states(self):
        html = page_html()
        for token in ("prefers-reduced-motion", 'id="motion-toggle"', 'id="mission-strip"'):
            self.assertIn(token, html)
        for forbidden in ("innerHTML", "setInterval"):
            self.assertNotIn(forbidden, html)

        r1 = project_task(dict(id="R01", protocol_version=2, current_round="r1", goal="前置任务", rounds=[dict(id="r1", state="review_passed", phase="done", todos=[dict(title="步骤1", status="done")], attempts=[], evidence=[])]), {})
        r2 = project_task(dict(id="R02", protocol_version=2, current_round="r2", goal="进行中任务", rounds=[dict(id="r2", state="implementing", phase="implementation", todos=[dict(title="步骤A", status="done"), dict(title="步骤B", status="pending")], attempts=[], evidence=[])]), {})
        r3 = project_task(dict(id="R03", protocol_version=2, current_round="r3", goal="待开工任务", rounds=[dict(id="r3", state="created", phase="planning", todos=[], attempts=[], evidence=[])]), {})
        waiting_signoff = project_task(dict(id="R04", protocol_version=2, current_round="r4", goal="待验收任务", rounds=[dict(id="r4", state="review_passed", phase="done", todos=[], attempts=[], evidence=[])]), {})
        rejected = project_task(dict(id="R05", protocol_version=2, current_round="r5", goal="被打回任务", rounds=[dict(id="r5", state="review_failed", phase="review", todos=[], attempts=[], evidence=[dict(kind="review", valid=True, data=dict(axes=dict(spec=dict(conclusion="pass", findings=[]), standards=dict(conclusion="fail", findings=[dict(message="修复问题", required=True, resolved=False)]))))])]), {})
        r2_verifying = project_task(dict(id="R02", protocol_version=2, current_round="r2", goal="进行中任务", rounds=[dict(id="r2", state="running", phase="verification", todos=[dict(title="步骤A", status="done"), dict(title="步骤B", status="done")], attempts=[], evidence=[])]), {})

        stub = r'''class Node {
          constructor(tag) { this.tag=tag;this.children=[];this.style={};this.dataset={};this.open=false;this.hidden=false;this.value='';this.content='';this.events={};this.isConnected=true; }
          set textContent(v) { this.content=String(v);this.children=[]; }
          get textContent() { return this.content+this.children.map(n=>n.textContent).join(' '); }
          append(...nodes) { this.children.push(...nodes); }
          replaceChildren(...nodes) { this.content='';this.children=nodes; }
          addEventListener(name, handler) { this.events[name]=handler; }
          toggle(open) { this.open=open;this.events.toggle?.(); }
        }
        const nodes={}; const document={createElement:tag=>new Node(tag),getElementById:id=>nodes[id]||(nodes[id]=new Node('div'))};
        function walk(n) { return [n,...n.children.flatMap(walk)]; }
        '''
        script = html.split("<script>")[1].split("</script>")[0].split("byId('refresh').addEventListener")[0]
        fixtures = dict(r1=r1, r2=r2, r3=r3, waitingSignoff=waiting_signoff, rejected=rejected, r2Verifying=r2_verifying)
        checks = r'''
        const nowSec = Math.floor(Date.now() / 1000);
        nodes['state-filter'] = new Node('select'); nodes['state-filter'].value = 'all';
        nodes['tier-filter'] = new Node('select'); nodes['tier-filter'].value = 'all';
        const freshR2 = {...fx.r2, updated_at: nowSec - 30};
        if (pickSpotlightTask([fx.r1, freshR2, fx.r3]).id !== 'R02') throw Error('应选中进行中任务作为聚光灯');
        renderTasks([fx.r1, freshR2, fx.r3]);
        const strip = nodes['mission-strip'];
        if (strip.hidden !== false) throw Error('多任务时应展示顶部串行总览');
        const mNodes = walk(strip).filter(n => n.className === 'mission-node');
        const mLinks = walk(strip).filter(n => n.className === 'mission-link');
        if (mNodes.length !== 3 || mLinks.length !== 2) throw Error('顶部总览节点或连线数量错误');
        const cards = nodes.tasks.children;
        if (cards[1].dataset.spotlight !== 'true' || cards[0].dataset.compact !== 'true') throw Error('卡片聚光灯或紧凑折叠状态错误');
        const botR2 = walk(cards[1]).find(n => n.className === 'cyber-bot');
        if (!botR2 || botR2.dataset.botMood !== 'code') throw Error('实施阶段机器人应为编码状态');

        renderTasks([{...fx.r2, updated_at: nowSec - 600}]);
        const staleBot = walk(nodes.tasks.children[0]).find(n => n.className === 'cyber-bot');
        if (!staleBot || staleBot.dataset.botMood !== 'sleep') throw Error('超过 5 分钟未更新的非终态任务机器人应自动休眠');

        renderTasks([{...fx.waitingSignoff, updated_at: nowSec - 7200}]);
        const trayCard = nodes.tasks.children[0];
        const trayBot = walk(trayCard).find(n => n.className === 'cyber-bot');
        const pipeNodesWait = walk(trayCard).filter(n => n.className === 'pipe-node');
        if (!trayBot || trayBot.dataset.botMood !== 'tray') throw Error('待人工验收终态机器人应举托盘而非休眠');
        if (pipeNodesWait[4].dataset.step !== 'wait') throw Error('待人工验收阶段 5 应为 wait 状态');

        renderTasks([{...fx.rejected, updated_at: nowSec - 20}]);
        const rejCard = nodes.tasks.children[0];
        const rejBot = walk(rejCard).find(n => n.className === 'cyber-bot');
        const rejWires = walk(rejCard).filter(n => n.className === 'pipe-wire');
        if (!rejBot || rejBot.dataset.botMood !== 'alert') throw Error('评审打回机器人应为警示状态');
        if (rejWires[2].dataset.flow !== 'reverse') throw Error('评审打回前导连线应反向回流');

        renderTasks([{...fx.r2, updated_at: nowSec - 15}]);
        renderTasks([{...fx.r2Verifying, updated_at: nowSec - 5}]);
        const advCard = nodes.tasks.children[0];
        const advBot = walk(advCard).find(n => n.className === 'cyber-bot');
        const advNodes = walk(advCard).filter(n => n.className === 'pipe-node');
        if (!advBot || advBot.dataset.moving !== 'forward') throw Error('阶段推进时机器人应有前向移动标记');
        if (advNodes[2].dataset.justAdvanced !== 'true') throw Error('推进后的目标阶段应触发点亮标记');
        '''
        payload = f"\nconst fx={json.dumps(fixtures, ensure_ascii=False)};\n"
        result = subprocess.run(["node", "-e", stub + script + payload + checks], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_hook_heartbeat_wakes_and_stops_cyber_bot(self):
        import hashlib
        from pathlib import Path
        import tempfile
        import dashboard_data

        with tempfile.TemporaryDirectory() as tmp:
            db_dir = Path(tmp)
            sid = "sess-live-1"
            hb_file = db_dir / ("hook-session-" + hashlib.sha256(sid.encode()).hexdigest() + ".json")
            hb_file.write_text(json.dumps({"session_id": sid, "host": "claude", "last_event": "PreToolUse", "last_tool": "Edit", "updated_at": 1234.5}), encoding="utf-8")
            hb = dashboard_data._session_heartbeat(db_dir, sid)
            self.assertEqual(hb, {"at": 1234.5, "host": "claude", "event": "PreToolUse", "tool": "Edit"})

            bad_sid = "sess-mismatch"
            bad_file = db_dir / ("hook-session-" + hashlib.sha256(bad_sid.encode()).hexdigest() + ".json")
            bad_file.write_text(json.dumps({"session_id": "other", "updated_at": 1234.5}), encoding="utf-8")
            self.assertIsNone(dashboard_data._session_heartbeat(db_dir, bad_sid))

            sym_sid = "sess-sym"
            sym_file = db_dir / ("hook-session-" + hashlib.sha256(sym_sid.encode()).hexdigest() + ".json")
            sym_file.symlink_to(hb_file)
            self.assertIsNone(dashboard_data._session_heartbeat(db_dir, sym_sid))

        if shutil.which("node"):
            r2 = project_task(dict(id="R02", protocol_version=2, current_round="r2", goal="进行中任务", rounds=[dict(id="r2", state="implementing", phase="implementation", todos=[dict(title="步骤A", status="done"), dict(title="步骤B", status="pending")], attempts=[], evidence=[])]), {})
            r2_running = project_task(dict(id="R02", protocol_version=2, current_round="r2", goal="进行中任务", rounds=[dict(id="r2", state="running", phase="verification", todos=[dict(title="步骤A", status="done"), dict(title="步骤B", status="done")], attempts=[], evidence=[])]), {})
            waiting_signoff = project_task(dict(id="R04", protocol_version=2, current_round="r4", goal="待验收任务", rounds=[dict(id="r4", state="review_passed", phase="done", todos=[], attempts=[], evidence=[])]), {})
            html = page_html()
            stub = r'''class Node {
              constructor(tag) { this.tag=tag;this.children=[];this.style={};this.dataset={};this.open=false;this.hidden=false;this.value='';this.content='';this.events={};this.isConnected=true; }
              set textContent(v) { this.content=String(v);this.children=[]; }
              get textContent() { return this.content+this.children.map(n=>n.textContent).join(' '); }
              append(...nodes) { this.children.push(...nodes); }
              replaceChildren(...nodes) { this.content='';this.children=nodes; }
              addEventListener(name, handler) { this.events[name]=handler; }
            }
            const nodes={}; const document={createElement:tag=>new Node(tag),getElementById:id=>nodes[id]||(nodes[id]=new Node('div'))};
            function walk(n) { return [n,...n.children.flatMap(walk)]; }
            '''
            script = html.split("<script>")[1].split("</script>")[0].split("byId('refresh').addEventListener")[0]
            checks = r'''
            const nowSec = Math.floor(Date.now() / 1000);
            nodes['state-filter'] = new Node('select'); nodes['state-filter'].value = 'all';
            nodes['tier-filter'] = new Node('select'); nodes['tier-filter'].value = 'all';

            renderTasks([{...fx.r2, updated_at: nowSec - 19 * 3600, heartbeat: {at: nowSec - 10, host: 'claude', event: 'PreToolUse', tool: 'Edit'}}]);
            let bot = walk(nodes.tasks.children[0]).find(n => n.className === 'cyber-bot');
            if (!bot || bot.dataset.botMood !== 'code' || bot.dataset.heartbeat !== 'live') throw Error('有实时心跳时机器人应处于唤醒工作态');
            if (!bot.textContent.includes('编辑中')) throw Error('实时工具心跳应展示当前动作：' + bot.textContent);

            renderTasks([{...fx.r2, updated_at: nowSec - 20, heartbeat: {at: nowSec - 5, host: 'claude', event: 'Stop', tool: ''}}]);
            bot = walk(nodes.tasks.children[0]).find(n => n.className === 'cyber-bot');
            if (!bot || bot.dataset.botMood !== 'sleep' || !bot.textContent.includes('回合待机')) throw Error('Stop 事件应让机器人进入回合待机');

            renderTasks([{...fx.r2, updated_at: nowSec - 19 * 3600, heartbeat: {at: nowSec - 600, host: 'claude', event: 'PreToolUse', tool: 'Bash'}}]);
            bot = walk(nodes.tasks.children[0]).find(n => n.className === 'cyber-bot');
            if (!bot || bot.dataset.botMood !== 'sleep') throw Error('心跳与更新均超 5 分钟时机器人应进入休眠');

            renderTasks([{...fx.waitingSignoff, updated_at: nowSec - 7200, heartbeat: {at: nowSec - 5, host: 'claude', event: 'Stop', tool: ''}}]);
            bot = walk(nodes.tasks.children[0]).find(n => n.className === 'cyber-bot');
            if (!bot || bot.dataset.botMood !== 'tray') throw Error('待人工验收终态即使 Stop 也必须举托盘');

            renderTasks([{...fx.r2Running, updated_at: nowSec - 900, heartbeat: {at: nowSec - 5, host: 'claude', event: 'Stop', tool: ''}}]);
            bot = walk(nodes.tasks.children[0]).find(n => n.className === 'cyber-bot');
            if (!bot || bot.dataset.botMood !== 'verify') throw Error('验证执行中（running）即使超 5 分钟或有 Stop 也不得休眠');
            '''
            payload = f"\nconst fx={json.dumps(dict(r2=r2, r2Running=r2_running, waitingSignoff=waiting_signoff), ensure_ascii=False)};\n"
            result = subprocess.run(["node", "-e", stub + script + payload + checks], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
