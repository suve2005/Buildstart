import React, { useState, useEffect } from 'react';

export default function BuildStartDashboard() {
  const [activeTab, setActiveTab] = useState('code');
  const [selectedRef, setSelectedRef] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');

  // Data States
  const [payments, setPayments] = useState([]);
  const [stats, setStats] = useState({ target_revenue: 0, verified_income: 0, discrepancy: 0 });
  const [activeProcesses, setActiveProcesses] = useState([]);
  const [paymentDetail, setPaymentDetail] = useState(null);

  // Define headers for authenticating with your FastAPI backend
  const apiHeaders = {
    'X-API-Key': import.meta.env.VITE_DASHBOARD_API_KEY || 'fallback_key_for_testing',
    'Content-Type': 'application/json'
  };

  // Fetch all initial dashboard data
  useEffect(() => {
    const fetchData = async () => {
      try {
        const [paymentsRes, statsRes, activeRes] = await Promise.all([
          fetch('http://localhost:8000/api/v1/payments', { headers: apiHeaders }),
          fetch('http://localhost:8000/api/v1/stats', { headers: apiHeaders }),
          fetch('http://localhost:8000/api/v1/active-processes', { headers: apiHeaders })
        ]);
        
        setPayments(await paymentsRes.json());
        setStats(await statsRes.json());
        setActiveProcesses(await activeRes.json());
      } catch (error) {
        console.error("Error connecting to backend:", error);
      }
    };
    fetchData();
  }, []);

  // Fetch detailed data when a specific payment is clicked
  const navigateToDetail = async (hash) => {
    try {
      const response = await fetch(`http://localhost:8000/api/v1/payments/${hash}`, { headers: apiHeaders });
      const data = await response.json();
      setPaymentDetail(data);
      setSelectedRef(hash);
      setActiveTab('detail');
    } catch (error) {
      console.error("Failed to load details", error);
    }
  };

  // Helper function to format UI icons based on status
  const getStatusIcon = (status) => {
    if (status === 'APPROVED') return <svg className="w-4 h-4 fill-[#3fb950]" viewBox="0 0 16 16"><path d="M13.78 4.22a.75.75 0 0 1 0 1.06l-7.25 7.25a.75.75 0 0 1-1.06 0L2.22 9.28a.751.751 0 0 1 .018-1.042.751.751 0 0 1 1.042-.018L6 10.94l6.72-6.72a.75.75 0 0 1 1.06 0Z"></path></svg>;
    if (status === 'NEEDS_VERIFICATION') return <svg className="w-4 h-4 fill-[#d29922]" viewBox="0 0 16 16"><path d="M8 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z"></path><path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0Z"></path></svg>;
    return <svg className="w-4 h-4 fill-[#f85149]" viewBox="0 0 16 16"><path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z"></path></svg>;
  };

  // Filter payments for the Search bar
  const filteredPayments = payments.filter(p => 
    p.reference_no?.toLowerCase().includes(searchQuery.toLowerCase()) || 
    p.phone_number?.includes(searchQuery)
  );

  return (
    <div className="min-h-screen bg-[#0d1117] text-[#c9d1d9] font-sans text-[14px]">
      
      {/* 1. GLOBAL HEADER */}
      <header className="bg-[#010409] border-b border-[#30363d] px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white font-bold shadow-md">
            V
          </div>
          <span className="text-[#c9d1d9] font-semibold text-[14px]">
            Admin <span className="text-[#8b949e] font-normal mx-1">/</span> Payment-Pipeline
          </span>
          <span className="border border-[#30363d] rounded-full px-2 py-0.5 text-xs text-[#8b949e] font-medium ml-2">Internal</span>
        </div>
        
        <div className="flex items-center gap-3">
          <div className="bg-[#0d1117] border border-[#30363d] rounded-md px-3 py-1.5 flex items-center gap-2 text-[#c9d1d9] w-72 focus-within:border-[#58a6ff] focus-within:ring-1 focus-within:ring-[#58a6ff] transition-all">
            <svg className="w-4 h-4 fill-[#8b949e]" viewBox="0 0 16 16"><path d="M10.68 11.74a6 6 0 0 1-7.922-8.982 6 6 0 0 1 8.982 7.922l3.04 3.04a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215ZM11.5 7a4.499 4.499 0 1 0-8.997 0A4.499 4.499 0 0 0 11.5 7Z"></path></svg>
            <input 
              type="text" 
              placeholder="Search features, orders, or references..." 
              className="bg-transparent border-none outline-none text-sm w-full placeholder-[#8b949e]"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
        </div>
      </header>

      {/* 2. SECONDARY HEADER (Repo Tabs) */}
      <div className="bg-[#0d1117] border-b border-[#30363d] pt-4 px-4 overflow-x-auto">
        <nav className="flex gap-2">
          {['code', 'process', 'issues', 'insights'].map((tab) => (
            <button 
              key={tab}
              onClick={() => setActiveTab(tab)} 
              className={`flex items-center gap-2 px-3 py-2 border-b-2 transition-colors capitalize ${activeTab === tab ? 'border-[#f78166] text-[#c9d1d9] font-semibold' : 'border-transparent text-[#8b949e] hover:bg-[#161b22] hover:rounded-t-md'}`}
            >
              {tab === 'code' ? 'Dashboard' : tab === 'issues' ? 'Needs Verification' : tab === 'insights' ? 'Insights & Reports' : 'Current Process'}
              {(tab === 'issues' || tab === 'process') && (
                <span className="bg-[#30363d] text-[#c9d1d9] text-xs px-2 py-0.5 rounded-full ml-1">
                  {tab === 'issues' ? payments.filter(p => p.status === 'NEEDS_VERIFICATION').length : activeProcesses.length}
                </span>
              )}
            </button>
          ))}
        </nav>
      </div>

      {/* 3. MAIN CONTENT */}
      <main className="max-w-[1280px] mx-auto mt-6 px-4 pb-12 grid grid-cols-1 md:grid-cols-4 gap-6">
        
        {/* LEFT COLUMN */}
        <div className="md:col-span-3 space-y-4">
          
          {/* TAB: Pipeline / Dashboard */}
          {activeTab === 'code' && (
            <>
              <div className="border border-[#30363d] rounded-md bg-[#0d1117] overflow-hidden">
                <div className="bg-[#161b22] border-b border-[#30363d] px-4 py-3 flex items-center justify-between text-sm text-[#8b949e]">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-[#c9d1d9]">Admin</span>
                    <span>System processed {payments.length} recent slips</span>
                  </div>
                </div>

                <div className="flex flex-col">
                  {filteredPayments.map((payment) => (
                    <div key={payment.image_hash} className="flex items-center justify-between border-b border-[#30363d] p-3 hover:bg-[#161b22] transition-colors group">
                      <div className="flex items-center gap-3 w-1/3">
                        {getStatusIcon(payment.status)}
                        <button onClick={() => navigateToDetail(payment.image_hash)} className="text-[#c9d1d9] hover:text-[#58a6ff] hover:underline font-medium truncate">
                          {payment.reference_no || payment.image_hash.substring(0,8)}
                        </button>
                      </div>
                      <div className="text-[#8b949e] truncate w-1/3 text-left hidden md:block text-sm">
                        {payment.phone_number} - Rs. {payment.amount || '0'}
                      </div>
                      <div className="text-[#8b949e] w-1/4 text-right text-sm flex items-center justify-end gap-3">
                        <span className={`font-mono px-1.5 rounded ${payment.confidence_score >= 80 ? 'text-[#3fb950] bg-[#3fb950]/10' : 'text-[#d29922] bg-[#d29922]/10'}`}>
                          {payment.confidence_score}%
                        </span>
                      </div>
                    </div>
                  ))}
                  {filteredPayments.length === 0 && (
                    <div className="p-8 text-center text-[#8b949e]">No payments match your search.</div>
                  )}
                </div>
              </div>

              {/* System Log */}
              <div className="border border-[#30363d] rounded-md bg-[#0d1117] mt-6">
                <div className="border-b border-[#30363d] p-3 flex items-center gap-2 font-semibold">
                  system_log.md
                </div>
                <div className="p-8 prose prose-invert max-w-none">
                  <h1 className="text-3xl font-bold border-b border-[#30363d] pb-2 mb-4 text-[#c9d1d9]">Payment Pipeline Status</h1>
                  <ul className="text-[#c9d1d9] mt-4 space-y-2 list-disc list-inside">
                    <li><strong>Average processing time:</strong> <span className="text-[#58a6ff] font-mono">1.24 seconds</span> per slip</li>
                    <li>Backend Connectivity: <span className={payments.length ? "text-[#3fb950]" : "text-[#d29922]"}>{payments.length ? "Online" : "Connecting..."}</span></li>
                  </ul>
                </div>
              </div>
            </>
          )}

          {/* TAB: Current Process */}
          {activeTab === 'process' && (
            <div className="border border-[#30363d] rounded-md bg-[#0d1117]">
              <div className="bg-[#161b22] border-b border-[#30363d] px-4 py-3 font-semibold text-[#c9d1d9] flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-[#d29922] animate-pulse"></span>
                {activeProcesses.length} Ongoing Pipeline Executions
              </div>

              {activeProcesses.map(process => (
                <div key={process.image_hash} className="p-4 border-b border-[#30363d] hover:bg-[#161b22] transition-colors">
                  <div className="flex justify-between items-start mb-3">
                    <div>
                      <div className="font-semibold text-[#c9d1d9] text-[15px]">Hash: {process.image_hash.substring(0, 10)}...</div>
                      <div className="text-xs text-[#8b949e] mt-0.5">Submitted by {process.phone_number}</div>
                    </div>
                    <span className="border border-[#1f6feb] text-[#58a6ff] bg-[#1f6feb]/10 px-2 py-0.5 rounded text-xs font-medium">
                      {process.status === 'AWAITING_SMS' ? 'Awaiting Bank SMS' : 'Running Validation'}
                    </span>
                  </div>
                </div>
              ))}
              {activeProcesses.length === 0 && <div className="p-8 text-center text-[#8b949e]">No processes currently running.</div>}
            </div>
          )}

          {/* TAB: Needs Verification */}
          {activeTab === 'issues' && (
            <div className="border border-[#30363d] rounded-md bg-[#0d1117]">
              {payments.filter(p => p.status === 'NEEDS_VERIFICATION').map(issue => (
                <div key={issue.image_hash} className="p-3 border-b border-[#30363d] hover:bg-[#161b22] flex gap-3">
                  {getStatusIcon(issue.status)}
                  <div>
                    <button onClick={() => navigateToDetail(issue.image_hash)} className="text-[#c9d1d9] font-semibold text-[15px] hover:text-[#58a6ff]">
                      {issue.reference_no || 'Unknown Ref'} : {issue.reason?.replace('_', ' ') || 'Manual Review Required'}
                    </button>
                    <div className="text-[#8b949e] text-xs mt-1">Submitted by {issue.phone_number}</div>
                  </div>
                </div>
              ))}
              {payments.filter(p => p.status === 'NEEDS_VERIFICATION').length === 0 && (
                <div className="p-8 text-center text-[#8b949e]">No payments require manual verification.</div>
              )}
            </div>
          )}

          {/* TAB: Insights */}
          {activeTab === 'insights' && (
            <div className="space-y-6">
              <div className="border border-[#30363d] rounded-md bg-[#0d1117]">
                <div className="bg-[#161b22] border-b border-[#30363d] p-3 font-semibold text-[#c9d1d9]">Financial Reconciliation</div>
                <div className="p-4 grid grid-cols-3 gap-4 text-center">
                  <div className="border-r border-[#30363d]">
                    <div className="text-[#8b949e] text-xs">Target Revenue</div>
                    <div className="text-xl font-semibold mt-1">Rs. {stats.target_revenue.toLocaleString()}</div>
                  </div>
                  <div className="border-r border-[#30363d]">
                    <div className="text-[#8b949e] text-xs">Verified Income</div>
                    <div className="text-xl font-semibold text-[#3fb950] mt-1">Rs. {stats.verified_income.toLocaleString()}</div>
                  </div>
                  <div>
                    <div className="text-[#8b949e] text-xs">Net Discrepancy</div>
                    <div className={`text-xl font-semibold mt-1 ${stats.discrepancy < 0 ? 'text-[#f85149]' : 'text-[#3fb950]'}`}>
                      Rs. {stats.discrepancy.toLocaleString()}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB: Detail View */}
          {activeTab === 'detail' && paymentDetail && (
            <div>
              <div className="mb-4 flex items-center justify-between border-b border-[#30363d] pb-4">
                <div>
                  <h1 className="text-2xl font-normal flex items-center gap-3 text-[#c9d1d9]">
                    {paymentDetail.payment.reference_no || 'Unknown Reference'}
                  </h1>
                </div>
                <button onClick={() => setActiveTab('code')} className="text-[#58a6ff] text-sm hover:underline">Return to queue</button>
              </div>

              {/* GitHub Split Diff View */}
              <div className="border border-[#30363d] rounded-md overflow-hidden bg-[#0d1117] flex">
                <div className="w-1/2 border-r border-[#30363d]">
                  <div className="bg-[#161b22] border-b border-[#30363d] p-3 text-sm font-semibold text-[#c9d1d9] flex justify-between">
                    SYSTEM CONCLUSION <span className="font-mono text-[#8b949e]">bot</span>
                  </div>
                  <div className="p-4 space-y-4 text-sm text-[#c9d1d9]">
                    <div className="flex justify-between border-b border-[#30363d] pb-2">
                      <span className="text-[#8b949e]">Confidence</span>
                      <span className="text-[#d29922] font-mono">{paymentDetail.payment.confidence_score}%</span>
                    </div>
                    <div className="flex justify-between border-b border-[#30363d] pb-2">
                      <span className="text-[#8b949e]">Status / Reason</span>
                      <span className="font-medium">{paymentDetail.payment.status} ({paymentDetail.payment.reason || 'N/A'})</span>
                    </div>
                  </div>
                </div>

                <div className="w-1/2">
                  <div className="bg-[#161b22] border-b border-[#30363d] p-3 text-sm font-semibold text-[#c9d1d9] flex justify-between">
                    CUSTOMER SUBMISSION <span className="font-mono text-[#8b949e]">user</span>
                  </div>
                  <div className="p-4 space-y-3 text-sm font-mono text-[#c9d1d9]">
                    <div className="px-3 py-1 text-[#8b949e]">Customer Phone: <span className="text-[#c9d1d9]">{paymentDetail.payment.phone_number}</span></div>
                    <div className="px-3 py-1 text-[#8b949e]">Submitted Amount: <span className="text-[#c9d1d9]">Rs. {paymentDetail.payment.amount}</span></div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}