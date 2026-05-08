import { render, screen } from '@testing-library/react'
import MessageBubble from '../../../src/components/chat/MessageBubble'

it('AGENT_003 显示"工具执行失败"标签', () => {
  render(<MessageBubble role="assistant" content="" isError errorCode="AGENT_003" />)
  expect(screen.getByText('工具执行失败')).toBeInTheDocument()
})

it('AGENT_001 显示"查询超时"标签', () => {
  render(<MessageBubble role="assistant" content="" isError errorCode="AGENT_001" />)
  expect(screen.getByText('查询超时')).toBeInTheDocument()
})

it('STREAM_ERROR 显示"连接中断，请重试"标签', () => {
  render(<MessageBubble role="assistant" content="" isError errorCode="STREAM_ERROR" />)
  expect(screen.getByText('连接中断，请重试')).toBeInTheDocument()
})

it('无 errorCode 时显示通用文案', () => {
  render(<MessageBubble role="assistant" content="" isError />)
  expect(screen.getByText('出现错误，请重试')).toBeInTheDocument()
})

it('有 errorHint 时渲染次要说明文字', () => {
  render(
    <MessageBubble
      role="assistant"
      content=""
      isError
      errorCode="AGENT_003"
      errorHint="MCP 工具执行失败: 字段 profit_rate 不存在"
    />
  )
  expect(screen.getByText('MCP 工具执行失败: 字段 profit_rate 不存在')).toBeInTheDocument()
})

it('无 errorHint 时不渲染次要说明文字', () => {
  render(<MessageBubble role="assistant" content="" isError errorCode="AGENT_003" />)
  expect(screen.queryByText(/MCP/)).not.toBeInTheDocument()
})
