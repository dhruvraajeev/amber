import { createBrowserRouter } from 'react-router'
import App from './App'
import Placeholder from './layout/Placeholder'

// Plan §11.1. /d/:designId and /sweep/:sweepId arrive with Part 3 (Steps 30, 32).
// Compare becomes CompareView in Step 8; share becomes SharedRunPage in Step 30.
export const router = createBrowserRouter([
  { path: '/', element: <App /> },
  { path: '/compare', element: <Placeholder title="Compare runs" body="Pin two runs in the editor to compare them here." /> },
  { path: '/share/:token', element: <Placeholder title="Shared run" body="Share links are not available yet." /> },
  { path: '*', element: <Placeholder title="Page not found" body="There is nothing at this address." /> },
])
