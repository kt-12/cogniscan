import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/sonner'
import './index.css'
import { Shell } from '@/components/Shell'
import { RunsPage } from '@/pages/RunsPage'
import { ViewerPage } from '@/pages/ViewerPage'

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } })

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={qc}>
    <TooltipProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Shell />}>
            <Route index element={<RunsPage />} />
            <Route path="/view/:id" element={<ViewerPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
      <Toaster richColors position="bottom-right" />
    </TooltipProvider>
  </QueryClientProvider>,
)
