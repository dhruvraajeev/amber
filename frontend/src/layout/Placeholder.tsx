import { Link } from 'react-router'
import TopBar from './TopBar'

// Stand-in page for routes whose real view comes in a later step.
export default function Placeholder({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex h-full flex-col">
      <TopBar />
      <main className="grid flex-1 place-items-center p-4">
        <div className="max-w-md rounded-lg border border-border bg-panel p-6 text-center">
          <h1 className="text-lg font-semibold">{title}</h1>
          <p className="mt-2 text-muted">{body}</p>
          <Link to="/" className="mt-4 inline-block text-accent hover:text-accent-2">
            Back to the editor
          </Link>
        </div>
      </main>
    </div>
  )
}
