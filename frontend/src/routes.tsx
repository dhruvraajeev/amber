import { createBrowserRouter } from 'react-router'
import App from './App'
import CompareView from './compare/CompareView'
import Placeholder from './layout/Placeholder'

// Plan §11.1.
export const router = createBrowserRouter([
  { path: '/', element: <App /> },
  { path: '/compare', element: <CompareView /> },
  { path: '*', element: <Placeholder title="Page not found" body="There is nothing at this address." /> },
])
