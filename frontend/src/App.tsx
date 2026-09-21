// Placeholder shell; Step 4 replaces this with the router and §11.2 layout.
export default function App() {
  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-border bg-panel px-4 py-2">
        <span className="font-semibold text-accent">◈ Amber</span>
      </header>
      <main className="grid flex-1 place-items-center">
        <div className="rounded-lg border border-border bg-panel p-6 text-center">
          <p className="text-muted">Canvas coming in Step 4.</p>
          <p className="num mt-3 flex gap-4">
            <span className="text-ok">● ok 42%</span>
            <span className="text-warn">▲ warn 78%</span>
            <span className="text-crit">■ crit 97%</span>
          </p>
        </div>
      </main>
    </div>
  )
}
