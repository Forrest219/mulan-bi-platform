import { render, screen } from '@testing-library/react'
import MessageBubble from '../../../src/components/chat/MessageBubble'

it('isError 时渲染实际 content 而非硬编码文案', () => {
  render(
    <MessageBubble
      role="assistant"
      content="⚠️ LLM 服务暂时不可用"
      isError
    />
  )
  expect(screen.getByText('⚠️ LLM 服务暂时不可用')).toBeInTheDocument()
  expect(screen.queryByText('连接中断，请重试。')).not.toBeInTheDocument()
})

it('isError 且 content 为空时回退到默认文案', () => {
  render(<MessageBubble role="assistant" content="" isError />)
  expect(screen.getByText('连接中断，请重试。')).toBeInTheDocument()
})
