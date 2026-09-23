import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router'
import { trackSpotlight } from './lib/spotlight'
import './styles/theme.css'
import { router } from './routes'

trackSpotlight()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
)
