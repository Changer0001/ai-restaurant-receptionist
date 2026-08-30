import React from 'react'

function App() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center">
      <div className="text-center">
        <h1 className="text-4xl font-bold text-gray-900 mb-4">
          AI Restaurant Receptionist
        </h1>
        <p className="text-xl text-gray-600 mb-8">
          Production-Ready Local-First MVP
        </p>
        <div className="space-y-4">
          <p className="text-gray-700">
            API Status: <span id="api-status">Checking...</span>
          </p>
          <a
            href="/docs"
            className="inline-block px-6 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition"
          >
            API Documentation
          </a>
        </div>
      </div>
    </div>
  )
}

export default App
