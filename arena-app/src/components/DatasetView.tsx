import { DatasetDetail, DatasetItem } from "./types";
import { Lang, t } from "../i18n";

interface DatasetViewProps {
  dataset: DatasetDetail;
  lang: Lang;
  onBack: () => void;
}

export function DatasetView({ dataset, lang, onBack }: DatasetViewProps) {
  return (
    <section className="card">
      <div className="section-head">
        <div>
          <p className="eyebrow">{t(lang, "datasetsTag")}</p>
          <h2>{dataset.dataset}</h2>
        </div>
        <button className="secondary" onClick={onBack}>
          {t(lang, "backToList")}
        </button>
      </div>
      <p className="muted">{dataset.description}</p>
      <p className="meta" style={{ marginBottom: "1rem" }}>
        {t(lang, "items", { count: dataset.items.length })} · {dataset.version} · {dataset.created_at}
      </p>
      <div className="stack">
        {dataset.items.map((item: DatasetItem) => (
          <div key={item.id} className="list-row">
            <div style={{ flex: 1 }}>
              <strong>{item.title}</strong>
              <p style={{ color: "#64748b", fontSize: "0.875rem" }}>
                {item.origin} · {item.category} · {t(lang, "expected")}: {item.expected_band}
              </p>
              {item.summary_excerpt && (
                <p style={{ color: "#94a3b8", fontSize: "0.8rem", marginTop: "0.25rem" }}>
                  {item.summary_excerpt.slice(0, 150)}...
                </p>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
