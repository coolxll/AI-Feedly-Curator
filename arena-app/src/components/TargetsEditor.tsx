import { Lang, t } from "../i18n";

interface TargetsEditorProps {
  targets: string[];
  lang: Lang;
  onChange: (targets: string[]) => void;
  onSave: (targets: string[]) => void;
}

export function TargetsEditor({ targets, lang, onChange, onSave }: TargetsEditorProps) {
  function updateTargetSpec(index: number, nextSpec: string) {
    const nextTargets = [...targets];
    nextTargets[index] = nextSpec;
    onChange(nextTargets);
  }

  function removeTarget(index: number) {
    const nextTargets = targets.filter((_, i) => i !== index);
    onChange(nextTargets);
  }

  function addTarget() {
    onChange([...targets, "name|model|url|key"]);
  }

  return (
    <section className="card">
      <div className="section-head">
        <div>
          <p className="eyebrow">{t(lang, "navTargets")}</p>
          <h2>{t(lang, "targetsTitle")}</h2>
        </div>
        <div style={{ display: "flex", gap: "10px" }}>
          <button className="secondary" onClick={addTarget}>{t(lang, "addTarget")}</button>
          <button className="primary" onClick={() => onSave(targets)}>{t(lang, "saveTargets")}</button>
        </div>
      </div>
      <div className="stack">
        {targets.map((target, idx) => {
          const parts = target.split("|");
          return (
            <div key={idx} className="target-row">
              <input
                className="target-input"
                placeholder={t(lang, "targetName")}
                value={parts[0] || ""}
                onChange={(e) => {
                  parts[0] = e.target.value;
                  updateTargetSpec(idx, parts.join("|"));
                }}
              />
              <input
                className="target-input"
                placeholder={t(lang, "targetModel")}
                value={parts[1] || ""}
                onChange={(e) => {
                  parts[1] = e.target.value;
                  updateTargetSpec(idx, parts.join("|"));
                }}
              />
              <input
                className="target-input"
                placeholder={t(lang, "targetBaseUrl")}
                value={parts[2] || ""}
                onChange={(e) => {
                  parts[2] = e.target.value;
                  updateTargetSpec(idx, parts.join("|"));
                }}
              />
              <input
                className="target-input"
                placeholder={t(lang, "targetEnvKey")}
                value={parts[3] || ""}
                onChange={(e) => {
                  parts[3] = e.target.value;
                  updateTargetSpec(idx, parts.join("|"));
                }}
              />
              <button className="btn-icon" onClick={() => removeTarget(idx)}>×</button>
            </div>
          );
        })}
      </div>
    </section>
  );
}
