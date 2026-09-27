import { useEffect, useMemo, useState, type ChangeEvent } from "react";
import { useStudio } from "../StudioContext";
import { Icon } from "../components/Icon";
import { Badge, Button, EmptyState, Field, PageHeader, Panel, Segmented } from "../components/ui";
import { ProjectLessonPanel } from "../components/ProjectLessonPanel";
import { playAudioOrSpeech } from "../lib/audio";
import { calculateDeliveryReadiness } from "../lib/deliveryReadiness";
import { exportProjectLines, downloadTextFile, parseDialogueFile } from "../lib/importers";
import { formatClock, formatDuration, jobStatusLabel, jobStatusTone, projectKindLabel, relativeTime } from "../lib/format";
import { navigate } from "../lib/navigation";
import type { DialogueLine, DialogueLinePatch, ImportPreview } from "../types";

type WorkspaceTab = "overview" | "lines" | "casting" | "takes" | "io" | "lesson";

const workspaceTabs: { value: WorkspaceTab; label: string; icon: "grid" | "edit" | "users" | "headphones" | "upload" | "file" }[] = [
  { value: "overview", label: "概览", icon: "grid" },
  { value: "lines", label: "台词编辑", icon: "edit" },
  { value: "casting", label: "角色映射", icon: "users" },
  { value: "takes", label: "候选 Take", icon: "headphones" },
  { value: "io", label: "导入 / 导出", icon: "upload" },
  { value: "lesson", label: "日语课程", icon: "file" },
];

const editablePatch = (line: DialogueLine): DialogueLinePatch => ({
  sceneId: line.sceneId,
  startMs: line.startMs,
  endMs: line.endMs,
  sourceText: line.sourceText,
  text: line.text,
  locale: line.locale,
  speakerId: line.speakerId,
  listener: line.listener,
  intent: line.intent,
  subtext: line.subtext,
  emotion: line.emotion,
  emotionIntensity: line.emotionIntensity,
  pace: line.pace,
  pitch: line.pitch,
  volume: line.volume,
  breath: line.breath,
  pause: line.pause,
  pronunciation: line.pronunciation,
  durationBudgetMs: line.durationBudgetMs,
  voiceProfileId: line.voiceProfileId,
  engineId: line.engineId,
  seed: line.seed,
  selectionLocked: line.selectionLocked,
});

const LineStatus = ({ line, takeCount }: { line: DialogueLine; takeCount: number }) => {
  if (line.stale) return <Badge tone="purple">需重算</Badge>;
  if (!line.voiceProfileId) return <Badge tone="warning">未映射声音</Badge>;
  if (line.selectedTakeId) return <Badge tone="success">已选定</Badge>;
  if (takeCount) return <Badge tone="info">{takeCount} 个候选</Badge>;
  return <Badge tone="neutral">待生成</Badge>;
};

export const WorkspacePage = ({ projectId }: { projectId: string }) => {
  const {
    snapshot,
    updateLine,
    importLines,
    generateTakes,
    selectTake,
    updateCharacter,
    operation,
    connectionMode,
  } = useStudio();
  const project = snapshot?.projects.find((candidate) => candidate.id === projectId);
  const lines = useMemo(() => snapshot?.lines.filter((line) => line.projectId === projectId).sort((a, b) => a.index - b.index) ?? [], [projectId, snapshot]);
  const characters = snapshot?.characters.filter((character) => character.projectId === projectId) ?? [];
  const projectJobs = snapshot?.jobs.filter((job) => job.projectId === projectId) ?? [];
  const [tab, setTab] = useState<WorkspaceTab>("overview");
  const [selectedLineId, setSelectedLineId] = useState<string | null>(lines[0]?.id ?? null);
  const [draft, setDraft] = useState<DialogueLine | null>(lines[0] ? structuredClone(lines[0]) : null);
  const [query, setQuery] = useState("");
  const [lineFilter, setLineFilter] = useState<"all" | "unmapped" | "unselected" | "stale">("all");
  const [takeCount, setTakeCount] = useState(3);
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null);
  const [importName, setImportName] = useState("");
  const [importError, setImportError] = useState<string | null>(null);
  const [exportFormat, setExportFormat] = useState<"json" | "jsonl" | "csv">("json");

  const selectedLine = lines.find((line) => line.id === selectedLineId) ?? lines[0] ?? null;
  const dirty = Boolean(selectedLine && draft && JSON.stringify(editablePatch(selectedLine)) !== JSON.stringify(editablePatch(draft)));

  useEffect(() => {
    if (!selectedLineId && lines[0]) setSelectedLineId(lines[0].id);
  }, [lines, selectedLineId]);

  useEffect(() => {
    if (selectedLine) setDraft(structuredClone(selectedLine));
    else setDraft(null);
  }, [selectedLine?.id, selectedLine?.revision]);

  useEffect(() => {
    const saveShortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s" && dirty && draft && selectedLine) {
        event.preventDefault();
        void updateLine(projectId, selectedLine.id, editablePatch(draft), selectedLine.revision);
      }
    };
    window.addEventListener("keydown", saveShortcut);
    return () => window.removeEventListener("keydown", saveShortcut);
  }, [dirty, draft, projectId, selectedLine, updateLine]);

  const chooseLine = (line: DialogueLine) => {
    if (dirty && !window.confirm("当前台词有未保存修改。放弃修改并切换吗？")) return;
    setSelectedLineId(line.id);
  };

  const filteredLines = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return lines.filter((line) => {
      const matchesQuery = !normalized || `${line.lineId} ${line.sceneId} ${line.text} ${line.sourceText} ${line.emotion}`.toLowerCase().includes(normalized);
      const takeCountForLine = snapshot?.takes.filter((take) => take.lineId === line.id).length ?? 0;
      const matchesFilter =
        lineFilter === "all" ||
        (lineFilter === "unmapped" && !line.voiceProfileId) ||
        (lineFilter === "unselected" && takeCountForLine > 0 && !line.selectedTakeId) ||
        (lineFilter === "stale" && line.stale);
      return matchesQuery && matchesFilter;
    });
  }, [lineFilter, lines, query, snapshot]);

  const currentTakes = snapshot?.takes.filter((take) => take.lineId === selectedLine?.id).sort((a, b) => a.index - b.index) ?? [];
  const readiness = calculateDeliveryReadiness(lines);
  const { unmapped, unselected: withoutSelection, stale } = readiness.blockers;

  const saveDraft = async () => {
    if (!draft || !selectedLine) return;
    await updateLine(projectId, selectedLine.id, editablePatch(draft), selectedLine.revision);
  };

  const handleFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setImportName(file.name);
    setImportError(null);
    try {
      const preview = await parseDialogueFile(file);
      setImportPreview(preview);
    } catch (error) {
      setImportPreview(null);
      setImportError(error instanceof Error ? error.message : "无法解析文件。请检查编码和格式。");
    }
    event.target.value = "";
  };

  if (!project) {
    return <Panel><EmptyState icon="alert" title="项目不存在" description="项目可能尚未从后端同步，或已被删除。" action={<Button onClick={() => navigate({ page: "projects" })}>返回项目首页</Button>} /></Panel>;
  }

  const overview = (
    <div className="workspace-overview">
      <div className="overview-metrics">
        <Panel><span className="overview-metric__icon"><Icon name="file" /></span><strong>{lines.length}</strong><span>台词总数</span><small>{new Set(lines.map((line) => line.sceneId)).size} 个场景</small></Panel>
        <Panel><span className="overview-metric__icon overview-metric__icon--warning"><Icon name="users" /></span><strong>{unmapped}</strong><span>未映射声音</span><small>{unmapped ? "导出前需要处理" : "角色映射完整"}</small></Panel>
        <Panel><span className="overview-metric__icon overview-metric__icon--purple"><Icon name="headphones" /></span><strong>{withoutSelection}</strong><span>尚未选 take</span><small>{lines.length - withoutSelection} 句已人工确认</small></Panel>
        <Panel><span className="overview-metric__icon overview-metric__icon--blue"><Icon name="retry" /></span><strong>{stale}</strong><span>受影响产物</span><small>仅局部重新计算</small></Panel>
      </div>
      <div className="overview-columns">
        <Panel className="readiness-card">
          <div className="panel-heading"><div><h2>交付准备度</h2><p>按真正阻塞导出的条件计算。</p></div><span className="readiness-score">{readiness.score}%</span></div>
          <div className="readiness-list">
            <button type="button" onClick={() => setTab("lines")}><span className={lines.length ? "is-done" : ""}><Icon name={lines.length ? "check" : "alert"} /></span><div><strong>台词已导入</strong><small>{lines.length ? `${lines.length} 句可编辑台词` : "请导入 SRT 或台词清单"}</small></div><Icon name="arrow" /></button>
            <button type="button" onClick={() => setTab("casting")}><span className={!unmapped ? "is-done" : "is-warning"}><Icon name={!unmapped ? "check" : "alert"} /></span><div><strong>角色与授权声音</strong><small>{unmapped ? `${unmapped} 句仍未映射` : "所有台词已映射"}</small></div><Icon name="arrow" /></button>
            <button type="button" onClick={() => setTab("takes")}><span className={!withoutSelection ? "is-done" : "is-warning"}><Icon name={!withoutSelection ? "check" : "headphones"} /></span><div><strong>候选 take 人工选择</strong><small>{withoutSelection ? `${withoutSelection} 句待选择` : "所有台词已选定"}</small></div><Icon name="arrow" /></button>
            <button type="button" onClick={() => setTab("io")}><span className={!stale ? "is-done" : "is-warning"}><Icon name={!stale ? "check" : "retry"} /></span><div><strong>产物有效性</strong><small>{stale ? `${stale} 句需要局部重算` : "没有过期产物"}</small></div><Icon name="arrow" /></button>
          </div>
        </Panel>
        <Panel className="project-activity">
          <div className="panel-heading"><div><h2>最近任务</h2><p>项目级运行与恢复历史。</p></div><Button tone="ghost" size="sm" onClick={() => navigate({ page: "tasks" })}>全局队列 <Icon name="arrow" size={14} /></Button></div>
          {projectJobs.slice(0, 5).map((job) => <div className="activity-row" key={job.id}><span className={`activity-dot activity-dot--${job.status}`} /><div><strong>{job.label}</strong><small>{job.stage} · {relativeTime(job.updatedAt)}</small></div><Badge tone={jobStatusTone(job.status)}>{jobStatusLabel[job.status]}</Badge></div>)}
          {!projectJobs.length ? <EmptyState icon="tasks" title="尚无任务" description="导入或生成后会记录在这里。" /> : null}
        </Panel>
      </div>
      <Panel className="quick-actions"><div><span><Icon name="spark" /></span><div><h3>继续当前项目</h3><p>建议先处理 {unmapped ? `${unmapped} 句未映射声音` : withoutSelection ? `${withoutSelection} 句候选选择` : "导出前质检"}。</p></div></div><div><Button icon="edit" onClick={() => setTab("lines")}>编辑台词</Button><Button tone="primary" icon="headphones" onClick={() => setTab("takes")}>比较候选</Button></div></Panel>
    </div>
  );

  const lineEditor = (
    <div className="line-editor-layout">
      <Panel padded={false} className="line-table-panel">
        <div className="line-toolbar"><div className="search-box"><Icon name="search" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索台词、场景、情绪…" /></div><select value={lineFilter} onChange={(event) => setLineFilter(event.target.value as typeof lineFilter)}><option value="all">全部状态</option><option value="unmapped">未映射声音</option><option value="unselected">有候选未选择</option><option value="stale">需要重算</option></select></div>
        <div className="line-table" role="table" aria-label="台词列表">
          <div className="line-table__head" role="row"><span># / 时间</span><span>角色</span><span>配音台词</span><span>情绪</span><span>状态</span></div>
          {filteredLines.map((line) => {
            const character = characters.find((candidate) => candidate.id === line.speakerId);
            const takeTotal = snapshot?.takes.filter((take) => take.lineId === line.id).length ?? 0;
            return <button type="button" className={`line-table__row ${selectedLine?.id === line.id ? "is-selected" : ""}`} key={line.id} onClick={() => chooseLine(line)} role="row"><span><strong>{String(line.index).padStart(2, "0")}</strong><small>{formatClock(line.startMs)}</small></span><span>{character ? <><i style={{ background: character.color }} />{character.name}</> : <em>未映射</em>}</span><span><strong>{line.text}</strong><small>{line.sourceText}</small></span><span>{line.emotion}<small>{line.emotionIntensity}%</small></span><span><LineStatus line={line} takeCount={takeTotal} /></span></button>;
          })}
          {!filteredLines.length ? <EmptyState icon="search" title="没有匹配台词" description="调整搜索词或状态筛选。" /> : null}
        </div>
      </Panel>
      <Panel className="line-inspector">
        {draft && selectedLine ? <>
          <header className="inspector-header"><div><span>逐句属性</span><h2>{draft.lineId}</h2></div><div>{dirty ? <Badge tone="warning" dot>未保存</Badge> : <Badge tone="success"><Icon name="check" size={12} />已同步</Badge>}</div></header>
          <div className="inspector-section"><h3>内容与时间</h3><Field label="原始台词"><textarea rows={2} value={draft.sourceText} onChange={(event) => setDraft({ ...draft, sourceText: event.target.value })} /></Field><Field label="配音台词" hint="超时优先改写台词或利用自然停顿，不默认暴力加速。"><textarea rows={3} value={draft.text} onChange={(event) => setDraft({ ...draft, text: event.target.value })} /></Field><div className="form-grid"><Field label="开始 ms"><input type="number" value={draft.startMs ?? ""} onChange={(event) => setDraft({ ...draft, startMs: event.target.value ? Number(event.target.value) : null })} /></Field><Field label="结束 ms"><input type="number" value={draft.endMs ?? ""} onChange={(event) => setDraft({ ...draft, endMs: event.target.value ? Number(event.target.value) : null })} /></Field><Field label="时长预算 ms" className="span-2"><input type="number" value={draft.durationBudgetMs ?? ""} onChange={(event) => setDraft({ ...draft, durationBudgetMs: event.target.value ? Number(event.target.value) : null })} /></Field></div></div>
          <div className="inspector-section"><h3>角色与上下文</h3><div className="form-grid"><Field label="说话角色"><select value={draft.speakerId ?? ""} onChange={(event) => { const character = characters.find((candidate) => candidate.id === event.target.value); setDraft({ ...draft, speakerId: event.target.value || null, voiceProfileId: character?.voiceProfileId ?? draft.voiceProfileId }); }}><option value="">未映射</option>{characters.map((character) => <option key={character.id} value={character.id}>{character.name}</option>)}</select></Field><Field label="听者"><input value={draft.listener} onChange={(event) => setDraft({ ...draft, listener: event.target.value })} /></Field><Field label="场景"><input value={draft.sceneId} onChange={(event) => setDraft({ ...draft, sceneId: event.target.value })} /></Field><Field label="意图"><input value={draft.intent} onChange={(event) => setDraft({ ...draft, intent: event.target.value })} /></Field><Field label="潜台词" className="span-2"><textarea rows={2} value={draft.subtext} onChange={(event) => setDraft({ ...draft, subtext: event.target.value })} /></Field></div></div>
          <div className="inspector-section"><h3>表演导演</h3><div className="form-grid"><Field label="情绪"><input value={draft.emotion} onChange={(event) => setDraft({ ...draft, emotion: event.target.value })} /></Field><Field label={`强度 ${draft.emotionIntensity}%`}><input type="range" min="0" max="100" value={draft.emotionIntensity} onChange={(event) => setDraft({ ...draft, emotionIntensity: Number(event.target.value) })} /></Field><Field label={`语速 ×${draft.pace.toFixed(2)}`}><input type="range" min="0.7" max="1.3" step="0.01" value={draft.pace} onChange={(event) => setDraft({ ...draft, pace: Number(event.target.value) })} /></Field><Field label={`音高 ${draft.pitch > 0 ? "+" : ""}${draft.pitch}`}><input type="range" min="-4" max="4" step="1" value={draft.pitch} onChange={(event) => setDraft({ ...draft, pitch: Number(event.target.value) })} /></Field><Field label="呼吸"><input value={draft.breath} onChange={(event) => setDraft({ ...draft, breath: event.target.value })} /></Field><Field label="停顿"><input value={draft.pause} onChange={(event) => setDraft({ ...draft, pause: event.target.value })} /></Field><Field label="发音提示" className="span-2"><input value={draft.pronunciation} onChange={(event) => setDraft({ ...draft, pronunciation: event.target.value })} /></Field></div></div>
          <div className="inspector-section"><h3>生成配置</h3><div className="form-grid"><Field label="声音配置"><select value={draft.voiceProfileId ?? ""} onChange={(event) => setDraft({ ...draft, voiceProfileId: event.target.value || null })}><option value="">未映射</option>{snapshot?.voices.map((voice) => <option key={voice.id} value={voice.id} disabled={voice.authorizationStatus !== "verified"}>{voice.name}{voice.authorizationStatus !== "verified" ? "（未授权）" : ""}</option>)}</select></Field><Field label="引擎"><select value={draft.engineId} onChange={(event) => setDraft({ ...draft, engineId: event.target.value })}>{snapshot?.engines.filter((engine) => engine.capabilities.includes("tts")).map((engine) => <option key={engine.id} value={engine.id}>{engine.name}</option>)}</select></Field><Field label="随机种子"><input type="number" value={draft.seed} onChange={(event) => setDraft({ ...draft, seed: Number(event.target.value) })} /></Field><Field label="人工锁定"><label className="switch-field"><input type="checkbox" checked={draft.selectionLocked} onChange={(event) => setDraft({ ...draft, selectionLocked: event.target.checked })} /><span />{draft.selectionLocked ? "已锁定" : "未锁定"}</label></Field></div></div>
          <footer className="inspector-footer"><span>{dirty ? "Ctrl+S 保存 · 修改生成字段会使下游候选过期" : `版本 ${selectedLine.revision}`}</span><div><Button tone="ghost" disabled={!dirty} onClick={() => setDraft(structuredClone(selectedLine))}>撤销本次编辑</Button><Button tone="primary" icon="check" disabled={!dirty} busy={operation === "保存台词"} onClick={() => void saveDraft()}>保存台词</Button></div></footer>
        </> : <EmptyState icon="edit" title="选择一条台词" description="在左侧选择台词后编辑完整导演属性。" />}
      </Panel>
    </div>
  );

  const casting = (
    <div className="casting-grid">{characters.length ? characters.map((character) => {
      const voice = snapshot?.voices.find((candidate) => candidate.id === character.voiceProfileId);
      const lineCount = lines.filter((line) => line.speakerId === character.id).length;
      return <Panel className="casting-card" key={character.id}><header><span className="character-avatar" style={{ "--avatar-color": character.color } as React.CSSProperties}>{character.name.slice(0, 1)}</span><div><h3>{character.name}</h3><p>{character.characterId} · {lineCount} 句台词</p></div><Badge tone={character.authorizationStatus === "verified" ? "success" : "warning"}>{character.authorizationStatus === "verified" ? "角色授权完整" : "授权待核"}</Badge></header><div className="casting-card__profile"><span><Icon name="headphones" /></span><div><small>当前声音</small><strong>{voice?.name ?? "未映射"}</strong><p>{voice?.description ?? "为角色选择一份已授权声音配置。"}</p></div></div><Field label="映射声音"><select value={character.voiceProfileId ?? ""} onChange={(event) => void updateCharacter(character.id, { voiceProfileId: event.target.value || null })}><option value="">未映射</option>{snapshot?.voices.map((profile) => <option key={profile.id} value={profile.id} disabled={profile.authorizationStatus !== "verified"}>{profile.name}</option>)}</select></Field><dl><div><dt>音色</dt><dd>{character.timbre}</dd></div><div><dt>说话习惯</dt><dd>{character.speechHabits}</dd></div><div><dt>礼貌层级</dt><dd>{character.politeness}</dd></div></dl></Panel>;
    }) : <Panel><EmptyState icon="users" title="尚未创建角色" description="导入带 speaker 字段的台词后，在后端建立角色档案。" /></Panel>}</div>
  );

  const takes = (
    <div className="takes-layout">
      <Panel className="take-line-picker"><div className="panel-heading"><div><h2>选择台词</h2><p>同一句可跨引擎生成多个候选并人工锁定。</p></div></div><div className="take-line-list">{lines.map((line) => <button type="button" key={line.id} className={selectedLine?.id === line.id ? "is-active" : ""} onClick={() => setSelectedLineId(line.id)}><span>{String(line.index).padStart(2, "0")}</span><div><strong>{line.text}</strong><small>{line.emotion} · {snapshot?.takes.filter((take) => take.lineId === line.id).length ?? 0} takes</small></div>{line.selectionLocked ? <Icon name="lock" size={14} /> : <Icon name="chevron" size={14} />}</button>)}</div></Panel>
      <section className="take-workspace">
        {selectedLine ? <>
          <Panel className="take-hero"><div><div className="eyebrow">{selectedLine.lineId} · {selectedLine.sceneId}</div><h2>{selectedLine.text}</h2><p>{selectedLine.sourceText}</p><div className="take-hero__tags"><Badge tone="purple">{selectedLine.emotion} {selectedLine.emotionIntensity}%</Badge><Badge>{selectedLine.engineId}</Badge><Badge>{formatDuration(selectedLine.durationBudgetMs)} 预算</Badge>{selectedLine.selectionLocked ? <Badge tone="success"><Icon name="lock" size={12} />人工锁定</Badge> : null}</div></div><div className="generate-box"><select value={takeCount} onChange={(event) => setTakeCount(Number(event.target.value))}><option value="2">2 个候选</option><option value="3">3 个候选</option><option value="4">4 个候选</option></select><Button tone="primary" icon="spark" busy={operation === "创建候选 take"} disabled={!selectedLine.voiceProfileId} onClick={() => void generateTakes(projectId, selectedLine.id, takeCount)}>生成候选</Button><small>{connectionMode === "mock" ? "Mock 只生成元数据，不加载 GPU" : "真实引擎任务进入串行 GPU 队列"}</small></div></Panel>
          {currentTakes.length ? <div className="take-grid">{currentTakes.map((take) => <Panel className={`take-card ${take.selected ? "is-selected" : ""}`} key={take.id}><header><div><span>TAKE {String(take.index).padStart(2, "0")}</span><Badge tone={take.status === "ready" ? "success" : take.status === "stale" ? "purple" : "warning"}>{take.status === "ready" ? "可试听" : take.status === "stale" ? "已过期" : take.status}</Badge></div><button className="take-play" type="button" aria-label={`播放 take ${take.index}`} onClick={() => playAudioOrSpeech(take.audioUrl, selectedLine.text, selectedLine.locale)}><Icon name="play" /></button></header><div className="fake-waveform" aria-hidden="true">{Array.from({ length: 28 }, (_, index) => <i key={index} style={{ height: `${18 + ((take.seed * (index + 3)) % 62)}%` }} />)}</div><div className="take-score"><div><span>质量提示</span><strong>{take.qualityScore ?? "—"}<small>/100</small></strong></div><div className="quality-track"><i style={{ width: `${take.qualityScore ?? 0}%` }} /></div><small>仅为 mock 可验证指标，不代表主观音质结论。</small></div><dl><div><dt>引擎</dt><dd>{take.engineId}</dd></div><div><dt>时长</dt><dd>{formatDuration(take.durationMs)}</dd></div><div><dt>响度</dt><dd>{take.loudnessLufs?.toFixed(1) ?? "—"} LUFS</dd></div><div><dt>Seed</dt><dd>{take.seed}</dd></div></dl><footer>{take.selected ? <Badge tone="success"><Icon name="check" size={13} />当前选定{selectedLine.selectionLocked ? " · 已锁" : ""}</Badge> : <span>输入哈希 {take.inputHash.slice(-8)}</span>}<Button tone={take.selected ? "ghost" : "default"} size="sm" icon={take.selected ? "lock" : "check"} disabled={take.status !== "ready"} onClick={() => void selectTake(projectId, selectedLine.id, take.id, true)}>{take.selected ? "保持选定" : "选择并锁定"}</Button></footer></Panel>)}</div> : <Panel><EmptyState icon="headphones" title="还没有候选 take" description={selectedLine.voiceProfileId ? "使用 mock 或真实引擎创建多个候选，再逐句试听选择。" : "请先在台词编辑或角色映射中选择已授权声音。"} action={<Button tone="primary" icon="spark" disabled={!selectedLine.voiceProfileId} onClick={() => void generateTakes(projectId, selectedLine.id, takeCount)}>生成 {takeCount} 个候选</Button>} /></Panel>}
        </> : <Panel><EmptyState icon="file" title="没有台词" description="先从 SRT、CSV、JSON 或 JSONL 导入台词。" /></Panel>}
      </section>
    </div>
  );

  const io = (
    <div className="io-grid">
      <Panel className="import-card"><div className="panel-heading"><div><h2>导入台词与字幕</h2><p>先在浏览器解析预览，确认后再写入项目。</p></div><span className="step-badge">1</span></div><label className="drop-zone"><input type="file" accept=".srt,.ass,.ssa,.csv,.json,.jsonl,.ndjson,.txt" onChange={(event) => void handleFile(event)} /><span><Icon name="upload" size={25} /></span><strong>选择或拖入台词文件</strong><small>SRT · ASS · CSV · JSON · JSONL · TXT，UTF-8 优先</small></label>{importError ? <div className="inline-error"><Icon name="alert" />{importError}</div> : null}{importPreview ? <div className="import-preview"><header><div><strong>{importName}</strong><small>{importPreview.format.toUpperCase()} · {importPreview.lines.length} 条有效台词</small></div><Badge tone={importPreview.warnings.length ? "warning" : "success"}>{importPreview.warnings.length ? `${importPreview.warnings.length} 个提示` : "校验通过"}</Badge></header>{importPreview.warnings.length ? <ul className="warning-list">{importPreview.warnings.slice(0, 4).map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}<div className="preview-table"><div><span>Line ID</span><span>Speaker</span><span>Text</span><span>时间 / 限制</span></div>{importPreview.lines.slice(0, 7).map((line, index) => <div key={`${line.lineId}-${index}`}><span>{line.lineId}</span><span>{line.speaker || "—"}</span><span>{line.text}</span><span>{formatDuration(line.durationLimitMs)}</span></div>)}</div>{importPreview.lines.length > 7 ? <small className="preview-more">另有 {importPreview.lines.length - 7} 条将在确认后导入</small> : null}<Button tone="primary" icon="check" busy={operation === "导入台词"} disabled={!importPreview.lines.length} onClick={() => void importLines(projectId, importPreview.lines).then((ok) => { if (ok) { setImportPreview(null); setImportName(""); } })}>确认导入 {importPreview.lines.length} 条</Button></div> : null}</Panel>
      <Panel className="export-card"><div className="panel-heading"><div><h2>规范化导出</h2><p>导出前明确显示阻塞项，不用空文件伪装完成。</p></div><span className="step-badge">2</span></div><div className="export-readiness"><div className={!unmapped ? "is-ready" : "is-blocked"}><Icon name={!unmapped ? "check" : "alert"} /><span><strong>声音映射</strong><small>{unmapped ? `${unmapped} 句未映射` : "完整"}</small></span></div><div className={!withoutSelection ? "is-ready" : "is-blocked"}><Icon name={!withoutSelection ? "check" : "alert"} /><span><strong>候选选择</strong><small>{withoutSelection ? `${withoutSelection} 句未选` : "完整"}</small></span></div><div className={!stale ? "is-ready" : "is-blocked"}><Icon name={!stale ? "check" : "retry"} /><span><strong>产物有效</strong><small>{stale ? `${stale} 句过期` : "完整"}</small></span></div></div><Field label="清单格式"><Segmented label="导出格式" value={exportFormat} options={[{ value: "json", label: "项目 JSON" }, { value: "jsonl", label: "JSONL" }, { value: "csv", label: "CSV" }]} onChange={(value) => setExportFormat(value as "json" | "jsonl" | "csv")} /></Field><div className="export-manifest"><h3>本次清单包含</h3><ul><li><Icon name="check" />稳定 line_id / scene_id / character_id</li><li><Icon name="check" />导演参数、声音、引擎与随机种子</li><li><Icon name="check" />selected_take_id 与人工锁定状态</li><li><Icon name="check" />时间窗与 duration_limit</li></ul></div><Button tone="primary" icon="download" disabled={!lines.length} onClick={() => { const file = exportProjectLines(project, lines, exportFormat); downloadTextFile(file.content, file.mime, file.fileName); }}>下载 {exportFormat.toUpperCase()} 清单</Button><small className="export-note">当前前端导出结构化清单；音频母版、视频、M&E 与 SRT/ASS 由后端导出任务提供。</small></Panel>
    </div>
  );

  return (
    <>
      <button type="button" className="back-link" onClick={() => navigate({ page: "projects" })}><Icon name="chevron" />返回项目首页</button>
      <PageHeader eyebrow={projectKindLabel[project.kind]} title={project.name} description={project.description || "为项目补充说明和交付目标。"} actions={<><Badge tone={project.status === "active" ? "success" : "neutral"} dot>{project.status === "active" ? "进行中" : "草稿"}</Badge><Button tone="ghost" icon="download" onClick={() => setTab("io")}>导出</Button></>} />
      <div className="workspace-tabs" role="tablist" aria-label="项目工作区">
        {workspaceTabs.map((item) => <button type="button" role="tab" aria-selected={tab === item.value} className={tab === item.value ? "is-active" : ""} key={item.value} onClick={() => setTab(item.value)}><Icon name={item.icon} /><span>{item.label}</span>{item.value === "lines" && lines.length ? <em>{lines.length}</em> : item.value === "takes" && withoutSelection ? <em>{withoutSelection}</em> : null}</button>)}
      </div>
      {tab === "overview" ? overview : tab === "lines" ? lineEditor : tab === "casting" ? casting : tab === "takes" ? takes : tab === "io" ? io : <ProjectLessonPanel project={project} lines={lines} characters={characters} />}
    </>
  );
};
