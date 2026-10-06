import Panel from '../../components/layout/Panel'
import PageHeader from '../../components/layout/PageHeader'
import ExtendedScopeBanner from '../../components/status/ExtendedScopeBanner'
import StatusPill from '../../components/status/StatusPill'

const HEADLINES = [
  { headline: 'NVIDIA supplier flags capacity constraints heading into Q3', source: 'Wire Service', sentiment: 'Negative', entities: ['NVDA'] },
  { headline: 'Fed commentary softens on near-term rate path', source: 'Macro Desk', sentiment: 'Positive', entities: ['Macro'] },
  { headline: 'Apple services segment beats consensus estimates', source: 'Earnings Wire', sentiment: 'Positive', entities: ['AAPL'] },
  { headline: 'Regulatory review opened into large-cap ad platforms', source: 'Policy Desk', sentiment: 'Negative', entities: ['GOOGL', 'META'] },
  { headline: 'Cloud infrastructure spend accelerates across hyperscalers', source: 'Sector Note', sentiment: 'Positive', entities: ['MSFT', 'AMZN'] },
]

export default function NewsExtraction() {
  return (
    <div className="qs-fade-in flex flex-col gap-6">
      <PageHeader
        title="Financial News Extraction"
        description="NLP-based extraction of entities, events and sentiment from unstructured financial news."
        breadcrumbs={[{ label: 'Intelligence', to: '/ml/models' }, { label: 'News Extraction' }]}
      />

      <ExtendedScopeBanner>
        This page previews a planned capability — an NLP pipeline that reads financial news and wires structured
        sentiment and entity signals into the risk model. It is not part of the current core demo flow, and the
        items below are static mock output rather than a live extraction pipeline.
      </ExtendedScopeBanner>

      <Panel title="Extraction Pipeline" subtitle="News → Entity Recognition → Event Classification → Sentiment → Feature Store">
        <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-text-secondary)]">
          {['Raw News Feed', 'Entity Recognition', 'Event Classification', 'Sentiment Scoring', 'Feature Store'].map((s, i, arr) => (
            <span key={s} className="flex items-center gap-2">
              <span className="rounded border border-[var(--color-border-strong)] px-2.5 py-1">{s}</span>
              {i < arr.length - 1 && <span className="text-[var(--color-text-muted)]">→</span>}
            </span>
          ))}
        </div>
      </Panel>

      <Panel title="Sample Extracted Headlines" bodyClassName="p-0">
        <div className="divide-y divide-[var(--color-border)]">
          {HEADLINES.map((h) => (
            <div key={h.headline} className="flex items-center justify-between gap-4 px-4 py-3">
              <div>
                <div className="text-sm text-[var(--color-text-primary)]">{h.headline}</div>
                <div className="mt-1 flex items-center gap-2 text-xs text-[var(--color-text-muted)]">
                  <span>{h.source}</span>
                  <span>·</span>
                  <span className="mono">{h.entities.join(', ')}</span>
                </div>
              </div>
              <StatusPill tone={h.sentiment === 'Positive' ? 'success' : 'danger'}>{h.sentiment}</StatusPill>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  )
}
