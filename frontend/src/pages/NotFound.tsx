import { Link } from 'react-router-dom';
import { usePlatformSettings } from './context/PlatformSettingsContext';

export default function NotFound() {
  const { settings } = usePlatformSettings();
  return (
    <div className="bg-white text-[#2C3E50] font-sans flex flex-col min-h-screen">
      {/* 1. Navigation Bar */}
      <header className="bg-white shadow-sm py-4 px-6 flex justify-between items-center">
        <div className="flex items-center">
          <Link to="/" className="text-2xl font-bold text-[#0A4D68]">
            {settings.platform_name}
          </Link>
        </div>
        <nav>
          <ul className="flex space-x-6">
            <li>
              <Link to="/" className="text-[#2C3E50] hover:text-[#0A4D68] transition-colors duration-200">
                首页
              </Link>
            </li>
            <li>
              <Link to="/login" className="text-[#2C3E50] hover:text-[#0A4D68] transition-colors duration-200">
                登录
              </Link>
            </li>
          </ul>
        </nav>
      </header>

      {/* 2. Hero Section */}
      <main className="flex-1 flex flex-col items-center justify-center px-6 py-24">
        <h1 className="text-8xl font-extrabold text-[#0A4D68] mb-4">404</h1>
        <h2 className="text-3xl font-bold text-[#2C3E50] mb-6">
          页面不存在
        </h2>
        <p className="text-lg text-[#607D8B] mb-10">
          您访问的页面 <span className="font-mono bg-gray-100 px-2 py-1 rounded">{settings.platform_name}</span> 不存在或已被移除
        </p>
        <div className="absolute inset-x-0 bottom-[-15%] sm:bottom-[-20%] md:bottom-[-25%] lg:bottom-[-30%] xl:bottom-[-35%]
                        text-[#34495E] opacity-20 font-extrabold
                        text-[12rem] sm:text-[18rem] md:text-[24rem] lg:text-[28rem] xl:text-[32rem]
                        leading-none select-none z-0">
          404
        </div>

        {/* Central Content Block */}
        <div className="relative z-10 max-w-lg mx-auto">
          {/* Main Error Message */}
          <h1 className="text-5xl md:text-6xl font-extrabold text-[#2C3E50] mb-4 leading-tight">
            Page Not Found
          </h1>
          <p className="text-xl text-[#5C6B7B] mb-8">
            抱歉，您访问的页面不存在或已被移除。
          </p>

          {/* Navigation Guidance Buttons */}
          <div className="flex flex-col sm:flex-row justify-center gap-4 mb-8">
            <Link
              to="/"
              className="inline-flex items-center justify-center px-6 py-3 border border-transparent text-base font-medium rounded-md shadow-sm
                         text-white bg-[#0A4D68] hover:bg-opacity-90 transition-colors duration-200
                         focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-[#0A4D68]"
            >
              返回首页
            </Link>
            <Link
              to="/contact"
              className="inline-flex items-center justify-center px-6 py-3 border border-[#0A4D68] text-base font-medium rounded-md
                         text-[#0A4D68] bg-white hover:bg-[#0A4D68] hover:text-white
                         transition-colors duration-200
                         focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-[#0A4D68]"
            >
              报告问题
            </Link>
          </div>

          {/* Secondary Contact Link */}
          <p className="text-lg text-[#5C6B7B]">
            如果问题持续存在，请联系技术支持
            <Link
              to="/contact"
              className="text-[#0A4D68] hover:underline font-semibold transition-colors duration-200 ml-1"
            >
              联系我们
            </Link>
          </p>
        </div>
      </main>

      {/* 3. Footer */}
      <footer className="bg-[#F8F8F8] py-6 px-6 text-center text-[#5C6B7B] text-sm mt-auto">
        <p>&copy; 2026 {settings.platform_name}. All rights reserved.</p>
        <div className="mt-2 space-x-4">
          <Link to="/privacy" className="hover:text-[#0A4D68] transition-colors duration-200">隐私政策</Link>
          <Link to="/terms" className="hover:text-[#0A4D68] transition-colors duration-200">服务条款</Link>
        </div>
      </footer>
    </div>
  );
}
