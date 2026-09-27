import { useMemo, useState } from "react";
import { useStudio } from "../StudioContext";
import { Icon } from "../components/Icon";
import { Badge, Button, EmptyState, PageHeader, Panel } from "../components/ui";
import { projectKindShort } from "../lib/format";

export const LibraryPage = () => {
  const { snapshot, updateCharacter, operation } = useStudio();
  const [projectId, setProjectId] = useState(snapshot?.projects[0]?.id ?? "all");
  const characters = useMemo(
    () => snapshot?.characters.filter((character) => projectId === "all" || character.projectId === projectId) ?? [],
    [projectId, snapshot],
  );

  return (
    <>
      <PageHeader eyebrow="Casting & consent" title="角色与声音库" description="角色档案与声音授权分开保存；未验证授权的声音不能进入生成任务。" />
      <Panel className="toolbar-panel">
        <div className="toolbar-label"><Icon name="users" /><span>查看项目</span></div>
        <select className="compact-select" value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="all">全部项目</option>{snapshot?.projects.map((project) => <option key={project.id} value={project.id}>{project.name} · {projectKindShort[project.kind]}</option>)}</select>
        <div className="toolbar-spacer" />
        <Badge tone="success">{snapshot?.voices.filter((voice) => voice.authorizationStatus === "verified").length ?? 0} 个已授权声音</Badge>
      </Panel>
      <div className="library-layout">
        <section>
          <div className="section-heading section-heading--small"><div><h2>角色档案</h2><p>为每个角色映射一份已授权声音配置。</p></div></div>
          {characters.length ? <div className="character-grid">{characters.map((character) => {
            const project = snapshot?.projects.find((candidate) => candidate.id === character.projectId);
            const voice = snapshot?.voices.find((candidate) => candidate.id === character.voiceProfileId);
            return (
              <Panel key={character.id} className="character-card">
                <header><span className="character-avatar" style={{ "--avatar-color": character.color } as React.CSSProperties}>{character.name.slice(0, 1)}</span><div><h3>{character.name}</h3><p>{character.characterId} · {project?.name}</p></div><Badge tone={character.authorizationStatus === "verified" ? "success" : character.authorizationStatus === "restricted" ? "danger" : "warning"}>{character.authorizationStatus === "verified" ? "授权已验证" : character.authorizationStatus === "pending" ? "待验证" : "受限"}</Badge></header>
                <dl><div><dt>身份</dt><dd>{character.identity}</dd></div><div><dt>年龄感</dt><dd>{character.ageImpression}</dd></div><div><dt>音色</dt><dd>{character.timbre}</dd></div><div><dt>说话习惯</dt><dd>{character.speechHabits}</dd></div></dl>
                <label className="mapping-field"><span>声音映射</span><select value={character.voiceProfileId ?? ""} onChange={(event) => void updateCharacter(character.id, { voiceProfileId: event.target.value || null })} disabled={operation === "保存角色映射"}><option value="">未映射</option>{snapshot?.voices.map((profile) => <option key={profile.id} value={profile.id} disabled={profile.authorizationStatus !== "verified"}>{profile.name}{profile.authorizationStatus !== "verified" ? "（未验证）" : ""}</option>)}</select></label>
                <footer>{voice ? <><Icon name="waveform" size={15} /><span>{voice.engineId}</span><em>{voice.locale}</em></> : <span className="warning-text"><Icon name="alert" size={14} />需要映射声音</span>}</footer>
              </Panel>
            );
          })}</div> : <Panel><EmptyState icon="users" title="没有角色档案" description="导入台词后可从 speaker 建立角色，或在后端创建角色档案。" /></Panel>}
        </section>
        <aside>
          <div className="section-heading section-heading--small"><div><h2>声音配置</h2><p>引擎映射、用途与授权状态。</p></div></div>
          <div className="voice-stack">{snapshot?.voices.map((voice) => (
            <Panel key={voice.id} className="voice-card">
              <header><span><Icon name="headphones" /></span><div><h3>{voice.name}</h3><p>{voice.engineId}</p></div></header>
              <p>{voice.description}</p>
              <div className="voice-card__meta"><Badge tone={voice.authorizationStatus === "verified" ? "success" : "warning"}>{voice.authorizationStatus === "verified" ? "授权已验证" : "待验证"}</Badge><span>{voice.locale}</span></div>
              <small><Icon name="lock" size={13} />{voice.licenseNote}</small>
              <Button tone="ghost" size="sm" icon="play" disabled>授权音频接入后试听</Button>
            </Panel>
          ))}</div>
        </aside>
      </div>
    </>
  );
};
