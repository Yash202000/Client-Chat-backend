"""
Pre-built System Workflow Templates
These templates are seeded into the database and available to all companies.
"""

SYSTEM_TEMPLATES = [
    {
        "name": "Customer Support FAQ",
        "description": "Handle common customer questions with AI-powered responses. Uses LLM to analyze questions and provide helpful answers.",
        "category": "Customer Support",
        "icon": "help-circle",
        "visual_steps": {
            "nodes": [
                {
                    "id": "start-1",
                    "type": "start",
                    "data": {"label": "Start"},
                    "position": {"x": 250, "y": 0}
                },
                {
                    "id": "llm-analyze",
                    "type": "llm",
                    "data": {
                        "label": "Analyze Question",
                        "prompt": "You are a helpful customer support assistant. Analyze the following customer question and provide a clear, helpful response.\n\nCustomer Question: {{context.user_message}}\n\nProvide a helpful and professional response.",
                        "model": "gpt-4o-mini",
                        "temperature": 0.7
                    },
                    "position": {"x": 250, "y": 100}
                },
                {
                    "id": "response-1",
                    "type": "response",
                    "data": {
                        "label": "Send Response",
                        "output_value": "{{llm-analyze.output}}"
                    },
                    "position": {"x": 250, "y": 200}
                }
            ],
            "edges": [
                {"id": "e1", "source": "start-1", "target": "llm-analyze", "sourceHandle": "output"},
                {"id": "e2", "source": "llm-analyze", "target": "response-1", "sourceHandle": "output"}
            ]
        },
        "trigger_phrases": ["help", "support", "question", "how do i", "what is"]
    },
    {
        "name": "Lead Qualification",
        "description": "Qualify leads by asking key questions about their needs, budget, and timeline. Score and categorize leads automatically.",
        "category": "Sales",
        "icon": "user-check",
        "visual_steps": {
            "nodes": [
                {
                    "id": "start-1",
                    "type": "start",
                    "data": {"label": "Start"},
                    "position": {"x": 250, "y": 0}
                },
                {
                    "id": "greeting",
                    "type": "response",
                    "data": {
                        "label": "Greeting",
                        "output_value": "Hi there! I'd love to learn more about your needs so I can help you better. Could you tell me what brings you here today?"
                    },
                    "position": {"x": 250, "y": 80}
                },
                {
                    "id": "listen-need",
                    "type": "listen",
                    "data": {
                        "label": "Listen for Need",
                        "variable_name": "customer_need",
                        "timeout": 300
                    },
                    "position": {"x": 250, "y": 160}
                },
                {
                    "id": "ask-timeline",
                    "type": "response",
                    "data": {
                        "label": "Ask Timeline",
                        "output_value": "Thanks for sharing! What's your timeline for getting started? Are you looking to begin within the next month, quarter, or is this more exploratory?"
                    },
                    "position": {"x": 250, "y": 240}
                },
                {
                    "id": "listen-timeline",
                    "type": "listen",
                    "data": {
                        "label": "Listen Timeline",
                        "variable_name": "timeline",
                        "timeout": 300
                    },
                    "position": {"x": 250, "y": 320}
                },
                {
                    "id": "llm-qualify",
                    "type": "llm",
                    "data": {
                        "label": "Qualify Lead",
                        "prompt": "Based on the following information, provide a lead qualification summary and next steps:\n\nCustomer Need: {{context.customer_need}}\nTimeline: {{context.timeline}}\n\nProvide:\n1. Lead quality score (Hot/Warm/Cold)\n2. Key interests\n3. Recommended next steps",
                        "model": "gpt-4o-mini",
                        "temperature": 0.5
                    },
                    "position": {"x": 250, "y": 400}
                },
                {
                    "id": "response-final",
                    "type": "response",
                    "data": {
                        "label": "Final Response",
                        "output_value": "Thank you for your time! Based on what you've shared, I'll make sure our team reaches out with relevant information. Is there anything else you'd like to know right now?"
                    },
                    "position": {"x": 250, "y": 480}
                }
            ],
            "edges": [
                {"id": "e1", "source": "start-1", "target": "greeting", "sourceHandle": "output"},
                {"id": "e2", "source": "greeting", "target": "listen-need", "sourceHandle": "output"},
                {"id": "e3", "source": "listen-need", "target": "ask-timeline", "sourceHandle": "output"},
                {"id": "e4", "source": "ask-timeline", "target": "listen-timeline", "sourceHandle": "output"},
                {"id": "e5", "source": "listen-timeline", "target": "llm-qualify", "sourceHandle": "output"},
                {"id": "e6", "source": "llm-qualify", "target": "response-final", "sourceHandle": "output"}
            ]
        },
        "trigger_phrases": ["interested in", "pricing", "demo", "learn more"]
    },
    {
        "name": "Appointment Booking",
        "description": "Guide users through booking an appointment. Collect preferred date, time, and contact information.",
        "category": "Scheduling",
        "icon": "calendar",
        "visual_steps": {
            "nodes": [
                {
                    "id": "start-1",
                    "type": "start",
                    "data": {"label": "Start"},
                    "position": {"x": 250, "y": 0}
                },
                {
                    "id": "greeting",
                    "type": "response",
                    "data": {
                        "label": "Booking Intro",
                        "output_value": "I'd be happy to help you schedule an appointment! What type of appointment would you like to book?"
                    },
                    "position": {"x": 250, "y": 80}
                },
                {
                    "id": "listen-type",
                    "type": "listen",
                    "data": {
                        "label": "Listen Type",
                        "variable_name": "appointment_type",
                        "timeout": 300
                    },
                    "position": {"x": 250, "y": 160}
                },
                {
                    "id": "ask-date",
                    "type": "response",
                    "data": {
                        "label": "Ask Date",
                        "output_value": "What date works best for you? Please share your preferred date."
                    },
                    "position": {"x": 250, "y": 240}
                },
                {
                    "id": "listen-date",
                    "type": "listen",
                    "data": {
                        "label": "Listen Date",
                        "variable_name": "preferred_date",
                        "timeout": 300
                    },
                    "position": {"x": 250, "y": 320}
                },
                {
                    "id": "ask-time",
                    "type": "response",
                    "data": {
                        "label": "Ask Time",
                        "output_value": "And what time would you prefer? Morning, afternoon, or evening?"
                    },
                    "position": {"x": 250, "y": 400}
                },
                {
                    "id": "listen-time",
                    "type": "listen",
                    "data": {
                        "label": "Listen Time",
                        "variable_name": "preferred_time",
                        "timeout": 300
                    },
                    "position": {"x": 250, "y": 480}
                },
                {
                    "id": "confirmation",
                    "type": "response",
                    "data": {
                        "label": "Confirm Booking",
                        "output_value": "I've noted your request for a {{context.appointment_type}} appointment on {{context.preferred_date}} in the {{context.preferred_time}}. Our team will confirm your booking shortly. Is there anything else I can help you with?"
                    },
                    "position": {"x": 250, "y": 560}
                }
            ],
            "edges": [
                {"id": "e1", "source": "start-1", "target": "greeting", "sourceHandle": "output"},
                {"id": "e2", "source": "greeting", "target": "listen-type", "sourceHandle": "output"},
                {"id": "e3", "source": "listen-type", "target": "ask-date", "sourceHandle": "output"},
                {"id": "e4", "source": "ask-date", "target": "listen-date", "sourceHandle": "output"},
                {"id": "e5", "source": "listen-date", "target": "ask-time", "sourceHandle": "output"},
                {"id": "e6", "source": "ask-time", "target": "listen-time", "sourceHandle": "output"},
                {"id": "e7", "source": "listen-time", "target": "confirmation", "sourceHandle": "output"}
            ]
        },
        "trigger_phrases": ["book", "appointment", "schedule", "meeting", "reserve"]
    },
    {
        "name": "Product Recommendation",
        "description": "Recommend products based on user preferences. Ask about needs, budget, and preferences to suggest the best options.",
        "category": "E-commerce",
        "icon": "shopping-bag",
        "visual_steps": {
            "nodes": [
                {
                    "id": "start-1",
                    "type": "start",
                    "data": {"label": "Start"},
                    "position": {"x": 250, "y": 0}
                },
                {
                    "id": "greeting",
                    "type": "response",
                    "data": {
                        "label": "Welcome",
                        "output_value": "Welcome! I'm here to help you find the perfect product. What are you looking for today?"
                    },
                    "position": {"x": 250, "y": 80}
                },
                {
                    "id": "listen-need",
                    "type": "listen",
                    "data": {
                        "label": "Listen Need",
                        "variable_name": "product_need",
                        "timeout": 300
                    },
                    "position": {"x": 250, "y": 160}
                },
                {
                    "id": "ask-budget",
                    "type": "response",
                    "data": {
                        "label": "Ask Budget",
                        "output_value": "Great choice! What's your budget range for this purchase?"
                    },
                    "position": {"x": 250, "y": 240}
                },
                {
                    "id": "listen-budget",
                    "type": "listen",
                    "data": {
                        "label": "Listen Budget",
                        "variable_name": "budget",
                        "timeout": 300
                    },
                    "position": {"x": 250, "y": 320}
                },
                {
                    "id": "llm-recommend",
                    "type": "llm",
                    "data": {
                        "label": "Generate Recommendations",
                        "prompt": "Based on the following customer preferences, provide 3 product recommendations:\n\nLooking for: {{context.product_need}}\nBudget: {{context.budget}}\n\nProvide:\n1. Top recommendation with brief description\n2. Alternative option\n3. Budget-friendly option\n\nFormat each with name, key features, and why it's a good fit.",
                        "model": "gpt-4o-mini",
                        "temperature": 0.7
                    },
                    "position": {"x": 250, "y": 400}
                },
                {
                    "id": "response-rec",
                    "type": "response",
                    "data": {
                        "label": "Show Recommendations",
                        "output_value": "Based on what you're looking for, here are my top recommendations:\n\n{{llm-recommend.output}}\n\nWould you like more details about any of these options?"
                    },
                    "position": {"x": 250, "y": 480}
                }
            ],
            "edges": [
                {"id": "e1", "source": "start-1", "target": "greeting", "sourceHandle": "output"},
                {"id": "e2", "source": "greeting", "target": "listen-need", "sourceHandle": "output"},
                {"id": "e3", "source": "listen-need", "target": "ask-budget", "sourceHandle": "output"},
                {"id": "e4", "source": "ask-budget", "target": "listen-budget", "sourceHandle": "output"},
                {"id": "e5", "source": "listen-budget", "target": "llm-recommend", "sourceHandle": "output"},
                {"id": "e6", "source": "llm-recommend", "target": "response-rec", "sourceHandle": "output"}
            ]
        },
        "trigger_phrases": ["recommend", "suggest", "looking for", "need help finding", "what should i buy"]
    },
    {
        "name": "Feedback Collection",
        "description": "Collect customer feedback with structured questions. Ask about satisfaction, suggestions, and overall experience.",
        "category": "Surveys",
        "icon": "message-square",
        "visual_steps": {
            "nodes": [
                {
                    "id": "start-1",
                    "type": "start",
                    "data": {"label": "Start"},
                    "position": {"x": 250, "y": 0}
                },
                {
                    "id": "intro",
                    "type": "response",
                    "data": {
                        "label": "Introduction",
                        "output_value": "We'd love to hear your feedback! Your input helps us improve. This will only take a minute. Ready to start?"
                    },
                    "position": {"x": 250, "y": 80}
                },
                {
                    "id": "listen-ready",
                    "type": "listen",
                    "data": {
                        "label": "Wait for Ready",
                        "variable_name": "ready_response",
                        "timeout": 300
                    },
                    "position": {"x": 250, "y": 160}
                },
                {
                    "id": "ask-satisfaction",
                    "type": "prompt",
                    "data": {
                        "label": "Ask Satisfaction",
                        "prompt_text": "On a scale of 1-5, how satisfied are you with our service?",
                        "options": ["1 - Very Dissatisfied", "2 - Dissatisfied", "3 - Neutral", "4 - Satisfied", "5 - Very Satisfied"],
                        "variable_name": "satisfaction_score"
                    },
                    "position": {"x": 250, "y": 240}
                },
                {
                    "id": "ask-improve",
                    "type": "response",
                    "data": {
                        "label": "Ask Improvement",
                        "output_value": "Thank you! What's one thing we could do better?"
                    },
                    "position": {"x": 250, "y": 320}
                },
                {
                    "id": "listen-improve",
                    "type": "listen",
                    "data": {
                        "label": "Listen Improvement",
                        "variable_name": "improvement_suggestion",
                        "timeout": 300
                    },
                    "position": {"x": 250, "y": 400}
                },
                {
                    "id": "thank-you",
                    "type": "response",
                    "data": {
                        "label": "Thank You",
                        "output_value": "Thank you so much for your feedback! We really appreciate you taking the time to help us improve. Have a great day!"
                    },
                    "position": {"x": 250, "y": 480}
                }
            ],
            "edges": [
                {"id": "e1", "source": "start-1", "target": "intro", "sourceHandle": "output"},
                {"id": "e2", "source": "intro", "target": "listen-ready", "sourceHandle": "output"},
                {"id": "e3", "source": "listen-ready", "target": "ask-satisfaction", "sourceHandle": "output"},
                {"id": "e4", "source": "ask-satisfaction", "target": "ask-improve", "sourceHandle": "output"},
                {"id": "e5", "source": "ask-improve", "target": "listen-improve", "sourceHandle": "output"},
                {"id": "e6", "source": "listen-improve", "target": "thank-you", "sourceHandle": "output"}
            ]
        },
        "trigger_phrases": ["feedback", "review", "rate", "survey", "opinion"]
    },
    {
        "name": "Order Status Check",
        "description": "Help customers check their order status. Collect order information and provide updates.",
        "category": "Customer Support",
        "icon": "package",
        "visual_steps": {
            "nodes": [
                {
                    "id": "start-1",
                    "type": "start",
                    "data": {"label": "Start"},
                    "position": {"x": 250, "y": 0}
                },
                {
                    "id": "greeting",
                    "type": "response",
                    "data": {
                        "label": "Greeting",
                        "output_value": "I can help you check your order status! Could you please provide your order number?"
                    },
                    "position": {"x": 250, "y": 80}
                },
                {
                    "id": "listen-order",
                    "type": "listen",
                    "data": {
                        "label": "Listen Order Number",
                        "variable_name": "order_number",
                        "timeout": 300
                    },
                    "position": {"x": 250, "y": 160}
                },
                {
                    "id": "llm-status",
                    "type": "llm",
                    "data": {
                        "label": "Generate Status",
                        "prompt": "A customer is asking about order number: {{context.order_number}}\n\nGenerate a realistic order status update that includes:\n1. Order confirmation\n2. Current status (processing/shipped/delivered)\n3. Estimated delivery date\n4. Next steps if any\n\nBe helpful and professional.",
                        "model": "gpt-4o-mini",
                        "temperature": 0.5
                    },
                    "position": {"x": 250, "y": 240}
                },
                {
                    "id": "response-status",
                    "type": "response",
                    "data": {
                        "label": "Show Status",
                        "output_value": "{{llm-status.output}}\n\nIs there anything else I can help you with regarding your order?"
                    },
                    "position": {"x": 250, "y": 320}
                }
            ],
            "edges": [
                {"id": "e1", "source": "start-1", "target": "greeting", "sourceHandle": "output"},
                {"id": "e2", "source": "greeting", "target": "listen-order", "sourceHandle": "output"},
                {"id": "e3", "source": "listen-order", "target": "llm-status", "sourceHandle": "output"},
                {"id": "e4", "source": "llm-status", "target": "response-status", "sourceHandle": "output"}
            ]
        },
        "trigger_phrases": ["order status", "where is my order", "track order", "delivery status", "shipping"]
    }
]
