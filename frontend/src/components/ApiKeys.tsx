import { useEffect, useState } from "react";
export interface BackendStatus { running: boolean; busy: boolean; message: string; modelSaved: boolean; embeddingSaved: boolean }
declare global { interface Window { senaDesktop?: {
  status(): Promise<BackendStatus>;
  saveKeys(keys: {model: string; embedding: string}): Promise<BackendStatus>;
  restart(): Promise<BackendStatus>;
} } }
export function ApiKeys() {
  const [status, setStatus] = useState<BackendStatus>();
  const [model, setModel] = useState("");
  const [embedding, setEmbedding] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    let active = true;
    const refresh = () => window.senaDesktop?.status().then(s => { if (active) setStatus(s); }).catch(() => {});
    void refresh(); const timer = setInterval(refresh, 1500);
    return () => { active = false; clearInterval(timer); };
  }, []);
  if (!window.senaDesktop) return <fieldset><legend>模型密钥</legend><p>请在 SenaBot 桌面窗口中配置 API Key。</p></fieldset>;
  const save = async () => {
    setSaving(true);
    try { setStatus(await window.senaDesktop!.saveKeys({model, embedding})); setModel(""); setEmbedding(""); }
    catch { setStatus(s => s && {...s, message: "保存失败，请重试"}); }
    finally { setSaving(false); }
  };
  const restart = async () => {
    setSaving(true);
    try { setStatus(await window.senaDesktop!.restart()); }
    catch { setStatus(s => s && {...s, message: "重启失败，请重试"}); }
    finally { setSaving(false); }
  };
  return <fieldset className="apiKeys"><legend>模型密钥</legend>
    <label>对话模型 API Key<input type="password" autoComplete="off" value={model} placeholder={status?.modelSaved ? "已保存，留空保留" : "请输入 API Key"} onChange={e => setModel(e.target.value)}/></label>
    <label>硅基流动 API Key<input type="password" autoComplete="off" value={embedding} placeholder={status?.embeddingSaved ? "已保存，留空保留" : "请输入 API Key"} onChange={e => setEmbedding(e.target.value)}/></label>
    <p className={`backendStatus ${status?.running ? "isRunning" : ""}`} role="status">{status?.message}</p>
    <div className="keyActions">
    <button type="button" className="saveButton" disabled={saving || status?.busy} onClick={save}>{saving ? "正在处理…" : "保存密钥并重启后端"}</button>
    <button type="button" className="saveButton" disabled={saving || status?.busy} onClick={restart}>重启后端</button>
    </div>
  </fieldset>;
}
