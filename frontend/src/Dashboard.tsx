import { useEffect, useState } from 'react'
import { Bar, Line } from 'react-chartjs-2'
import {
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Title,
  Tooltip,
} from 'chart.js'

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  Title,
  Tooltip,
  Legend,
)

const STORAGE_KEY = 'api_key'
const LAB_OPTIONS = ['lab-01', 'lab-02', 'lab-03', 'lab-04', 'lab-05']

interface ScoreBucket {
  bucket: string
  count: number
}

interface TimelinePoint {
  date: string
  submissions: number
}

interface PassRate {
  task: string
  avg_score: number
  attempts: number
}

interface DashboardData {
  scores: ScoreBucket[]
  timeline: TimelinePoint[]
  passRates: PassRate[]
}

interface DashboardProps {
  token: string
}

type DashboardState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'success'; data: DashboardData }

async function fetchJson<T>(path: string, token: string): Promise<T> {
  const response = await fetch(path, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }

  return response.json() as Promise<T>
}

export function Dashboard({ token }: DashboardProps) {
  const [selectedLab, setSelectedLab] = useState('lab-04')
  const [state, setState] = useState<DashboardState>({ status: 'loading' })

  useEffect(() => {
    const authToken = token || localStorage.getItem(STORAGE_KEY) || ''
    if (!authToken) {
      setState({ status: 'error', message: 'Missing API token.' })
      return
    }

    setState({ status: 'loading' })

    const query = new URLSearchParams({ lab: selectedLab }).toString()

    Promise.all([
      fetchJson<ScoreBucket[]>(`/analytics/scores?${query}`, authToken),
      fetchJson<TimelinePoint[]>(`/analytics/timeline?${query}`, authToken),
      fetchJson<PassRate[]>(`/analytics/pass-rates?${query}`, authToken),
    ])
      .then(([scores, timeline, passRates]) => {
        setState({
          status: 'success',
          data: { scores, timeline, passRates },
        })
      })
      .catch((error: Error) => {
        setState({ status: 'error', message: error.message })
      })
  }, [selectedLab, token])

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
  }

  return (
    <section className="dashboard-page">
      <div className="dashboard-toolbar">
        <label className="lab-picker" htmlFor="lab-select">
          Lab
        </label>
        <select
          id="lab-select"
          value={selectedLab}
          onChange={(event) => setSelectedLab(event.target.value)}
        >
          {LAB_OPTIONS.map((lab) => (
            <option key={lab} value={lab}>
              {lab}
            </option>
          ))}
        </select>
      </div>

      {state.status === 'loading' && <p>Loading dashboard...</p>}
      {state.status === 'error' && <p>Error: {state.message}</p>}

      {state.status === 'success' && (
        <>
          <div className="dashboard-grid">
            <article className="dashboard-card">
              <h2>Score Distribution</h2>
              <div className="chart-shell">
                <Bar
                  options={chartOptions}
                  data={{
                    labels: state.data.scores.map((entry) => entry.bucket),
                    datasets: [
                      {
                        label: 'Submissions',
                        data: state.data.scores.map((entry) => entry.count),
                        backgroundColor: '#216869',
                        borderRadius: 6,
                      },
                    ],
                  }}
                />
              </div>
            </article>

            <article className="dashboard-card">
              <h2>Timeline</h2>
              <div className="chart-shell">
                <Line
                  options={chartOptions}
                  data={{
                    labels: state.data.timeline.map((entry) => entry.date),
                    datasets: [
                      {
                        label: 'Submissions',
                        data: state.data.timeline.map(
                          (entry) => entry.submissions,
                        ),
                        borderColor: '#1f3c88',
                        backgroundColor: '#9dd9d2',
                        tension: 0.25,
                      },
                    ],
                  }}
                />
              </div>
            </article>
          </div>

          <article className="dashboard-card dashboard-table-card">
            <h2>Pass Rates</h2>
            <table>
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Avg score</th>
                  <th>Attempts</th>
                </tr>
              </thead>
              <tbody>
                {state.data.passRates.map((entry) => (
                  <tr key={entry.task}>
                    <td>{entry.task}</td>
                    <td>{entry.avg_score.toFixed(1)}</td>
                    <td>{entry.attempts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </article>
        </>
      )}
    </section>
  )
}
