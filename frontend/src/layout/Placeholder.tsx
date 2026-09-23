import { ArrowLeft } from 'lucide-react'
import { Link } from 'react-router'
import TopBar from './TopBar'

// Stand-in page for routes whose real view comes in a later step.
export default function Placeholder({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex h-full flex-col gap-3 p-3">
      <TopBar />
      <main className="panel grid flex-1 place-items-center p-4">
        <div className="max-w-md text-center">
          <h1 className="text-2xl font-semibold tracking-[-0.02em]">{title}</h1>
          <p className="mt-2 text-muted">{body}</p>
          <Link to="/" className="field mt-6 inline-flex h-10 items-center gap-2 rounded-full px-4 text-[13px] hover:text-text">
            <ArrowLeft size={15} aria-hidden />
            Back to the editor
          </Link>
        </div>
      </main>
    </div>
  )
}
