async function loadDashboard() {
    try {
        
        const response = await fetch('../data.json'); 
        const data = await response.json();

        document.getElementById('update-time').innerText = data.ultima_atualizacao;
        
        const grid = document.getElementById('dashboard-grid');
        grid.innerHTML = ''; 

        data.ativos.forEach(ativo => {
            const isUp = parseFloat(ativo.variacao) > 0;
            const card = document.createElement('div');
            card.className = 'card';
            
            card.innerHTML = `
                <div class="card-header">
                    <h2>${ativo.moeda}</h2>
                    <span>${ativo.emoji}</span>
                </div>
                <div class="price">$ ${ativo.preco}</div>
                <div class="variation ${isUp ? 'up' : 'down'}">
                    ${isUp ? '▲' : '▼'} ${ativo.variacao}% (Est. p/ amanhã)
                </div>
                <p>Status: <strong>${ativo.status}</strong></p>
                <a href="../${ativo.imagem}" target="_blank" class="chart-btn">Ver Gráfico de IA</a>
            `;
            grid.appendChild(card);
        });
    } catch (error) {
        console.error("Erro ao carregar dados:", error);
        document.getElementById('dashboard-grid').innerHTML = "<p>Dados ainda não disponíveis. O robô precisa rodar uma vez!</p>";
    }
}

window.onload = loadDashboard;